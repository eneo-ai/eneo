"""Orchestrate full and delta SharePoint syncs.

Owns pass ordering, token advancement and transaction-bound side effects.
Scope decisions and strict listing: sharepoint_scope.
Index mutations and content identity: SharePointIndex.
Full-sync orphan and moved-subtree cleanup: SharePointReconciliation.
Counts and result semantics: sharepoint_results.
What is kept about items between passes: sharepoint_sync_ledger.
Graph transport, parsing, credentials, progress and persisted status are owned
elsewhere; do not add another implementation of their rules here.
"""

import asyncio
import hashlib
import time
from collections.abc import Callable, Coroutine
from contextlib import AbstractAsyncContextManager, nullcontext
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import partial
from typing import TYPE_CHECKING, Any, Optional, cast
from uuid import UUID

import aiohttp
from sqlalchemy.ext.asyncio import AsyncSession as SqlAlchemyAsyncSession
from sqlalchemy.orm import Session

from eneo.database.transaction_callbacks import after_outer_transaction
from eneo.integration.domain.entities.oauth_token import OauthToken
from eneo.integration.domain.entities.sync_log import SyncLog
from eneo.integration.domain.entities.tenant_sharepoint_app import (
    TenantSharePointApp,
)
from eneo.integration.domain.repositories.integration_knowledge_repo import (
    SyncStateFields,
)
from eneo.integration.domain.skip_reasons import (
    error_skipped,
    skipped,
    skipped_by_code,
)
from eneo.integration.infrastructure.clients.sharepoint_content_client import (
    AccessTokenProvider,
    DeltaTokenExpiredException,
    SharePointContentClient,
)
from eneo.integration.infrastructure.content_service import (
    sharepoint_results as sync_results,
)
from eneo.integration.infrastructure.content_service import (
    sharepoint_scope as scope_rules,
)
from eneo.integration.infrastructure.content_service.parsing import (
    extract_text_from_canvas_layout,
    has_graph_facet,
    require_text,
)
from eneo.integration.infrastructure.content_service.sharepoint_index import (
    SharePointIndex,
)
from eneo.integration.infrastructure.content_service.sharepoint_reconciliation import (
    SharePointReconciliation,
)
from eneo.integration.infrastructure.content_service.sharepoint_results import (
    DeltaBaselineUnavailable,
    SyncAccessDenied,
    SyncDownloadsUnavailable,
    SyncItemsFailed,
)
from eneo.integration.infrastructure.content_service.sharepoint_sync_ledger import (
    MAX_FAILED_ITEMS,
    FailedItem,
    WalkGenerations,
    decode_failed_items,
    encode_failed_items,
)
from eneo.integration.infrastructure.content_service.sync_state import (
    SyncStateRecorder,
)
from eneo.integration.infrastructure.content_service.types import (
    SharePointItem,
    SharePointTokenProtocol,
    SyncStats,
)
from eneo.integration.infrastructure.content_service.utils import (
    file_extension_to_type,
)
from eneo.integration.infrastructure.graph_errors import ITEM_LEVEL_HTTP_STATUSES
from eneo.integration.infrastructure.office_change_key_service import (
    OfficeChangeKeyService,
)
from eneo.integration.infrastructure.sharepoint_sync_progress import (
    SharePointSyncProgressStore,
    SyncProgressReporter,
)
from eneo.main.logging import get_logger
from eneo.observability.error_text import user_visible_error

if TYPE_CHECKING:
    from eneo.database.database import AsyncSession
    from eneo.info_blobs.info_blob_service import InfoBlobService
    from eneo.integration.domain.entities.integration_knowledge import (
        IntegrationKnowledge,
    )
    from eneo.integration.domain.repositories.integration_knowledge_repo import (
        IntegrationKnowledgeRepository,
    )
    from eneo.integration.domain.repositories.oauth_token_repo import (
        OauthTokenRepository,
    )
    from eneo.integration.domain.repositories.sync_log_repo import (
        SyncLogRepository,
    )
    from eneo.integration.domain.repositories.tenant_sharepoint_app_repo import (
        TenantSharePointAppRepository,
    )
    from eneo.integration.infrastructure.auth_service.org_token_provider import (
        OrgTokenProvider,
    )
    from eneo.integration.infrastructure.oauth_token_service import (
        OauthTokenService,
    )
    from eneo.users.user import UserInDB


logger = get_logger(__name__)


def _log_pass_failure(context: str, failure: Exception) -> None:
    """A pass that could not finish every item is a designed outcome, not a fault."""
    if isinstance(failure, SyncItemsFailed):
        logger.warning("%s: %s", context, failure)
    else:
        logger.error("%s: %s", context, failure, exc_info=True)


class SimpleSharePointToken:
    """Simple token wrapper for SharePoint API calls.

    Used for tenant_app integrations where we don't have an OauthToken
    in the database, but need a token object with access_token attribute.
    """

    def __init__(self, access_token: str) -> None:
        super().__init__()
        self.access_token = access_token
        self.base_url = "https://graph.microsoft.com"


def _require_sharepoint_token(
    token: OauthToken | SimpleSharePointToken,
) -> SharePointTokenProtocol:
    if isinstance(token, SimpleSharePointToken):
        return token
    if token.is_sharepoint:
        return cast(SharePointTokenProtocol, token)
    raise ValueError("Expected a SharePoint token")


@dataclass
class _DeltaPass:
    """What one delta pass carries from entry to entry."""

    content_client: SharePointContentClient
    integration_knowledge: "IntegrationKnowledge"
    site_id: Optional[str]
    drive_id: str
    stats: SyncStats
    change_ids: set[str]
    scope_folder_path: Optional[str]
    folder_scope_path_unresolved: bool
    # The change set's folders that lie in scope, placed before any entry is
    # applied; see _place_folder_entries.
    known_subfolder_ids: set[str]
    # Processed (knowledge, item, change_key) triples, written to the Redis
    # ChangeKey cache only after the DB transaction commits; see
    # _schedule_post_commit_change_keys.
    pending_change_keys: list[tuple[UUID, str, str]]
    # Indexed item ids, read once per pass by the first entry that needs them.
    indexed_ids: set[str] | None = None
    # Where Graph put a folder entry that had no path and that the change set
    # could not place; None when Graph could not say.
    placements: dict[str, Optional[SharePointItem]] = field(
        default_factory=dict[str, Optional[SharePointItem]]
    )
    # Items earlier passes could not finish.
    failed_before: dict[str, FailedItem] = field(default_factory=dict[str, FailedItem])
    # Those of them this pass tried again outside the change set.
    retried_ids: set[str] = field(default_factory=set[str])
    # What the walk cache keys of this pass end with, read when first needed;
    # None when it could not be read and the cache is not used.
    walk_cache_suffix: Optional[str] = None
    walk_cache_suffix_read: bool = False


class SharePointContentService:
    def __init__(
        self,
        oauth_token_repo: "OauthTokenRepository",
        user: "UserInDB",
        info_blob_service: "InfoBlobService",
        integration_knowledge_repo: "IntegrationKnowledgeRepository",
        oauth_token_service: "OauthTokenService",
        session: "AsyncSession",
        tenant_sharepoint_app_repo: "TenantSharePointAppRepository",
        org_token_provider: "OrgTokenProvider",
        sync_log_repo: "SyncLogRepository | None" = None,
        change_key_service: "OfficeChangeKeyService | None" = None,
        sync_progress_store: SharePointSyncProgressStore | None = None,
        walk_generations: WalkGenerations | None = None,
    ) -> None:
        super().__init__()
        self.org_token_provider = org_token_provider
        self.oauth_token_repo = oauth_token_repo
        self.integration_knowledge_repo = integration_knowledge_repo
        self.oauth_token_service = oauth_token_service
        self.session = session
        self.tenant_sharepoint_app_repo = tenant_sharepoint_app_repo
        self._sync_state = SyncStateRecorder(integration_knowledge_repo, sync_log_repo)
        # Strong refs to in-flight post-transaction tasks (ChangeKey flushes,
        # progress clears) so the event loop does not GC them before they run.
        self._post_transaction_tasks: set["asyncio.Task[None]"] = set()
        self._index = SharePointIndex(
            info_blob_service, integration_knowledge_repo, user, change_key_service
        )
        self._reconciliation = SharePointReconciliation(self._index)
        # The walk cache lives in the ChangeKey Redis, and so does its generation.
        if walk_generations is None and isinstance(
            change_key_service, OfficeChangeKeyService
        ):
            walk_generations = WalkGenerations(change_key_service.redis_client)
        self._walk_generations = walk_generations
        self._clock: Callable[[], float] = time.time
        self._progress = SyncProgressReporter(
            sync_progress_store,
            after_transaction=partial(self._after_transaction, on_rollback=True),
        )

    async def _org_access_token(
        self, tenant_app: TenantSharePointApp
    ) -> tuple[str, AccessTokenProvider]:
        """An organisation token plus a re-acquire callback for long syncs.

        The provider records credential health and lets the Graph client
        re-acquire on 401, so a sync longer than one token lifetime survives.
        """
        access_token = await self.org_token_provider.get_access_token(tenant_app)
        return access_token, self.org_token_provider.access_token_provider(tenant_app)

    async def _graph_access(
        self,
        token_id: Optional[UUID],
        tenant_app_id: Optional[UUID],
        *,
        purpose: str,
    ) -> tuple[SharePointTokenProtocol, Optional[UUID], Optional[AccessTokenProvider]]:
        """The token Graph is called with, its OAuth row id and a re-acquire callback.

        A tenant app gets an organisation token from the provider; a personal
        integration uses the person's OAuth token and refreshes it by row id.
        """
        if tenant_app_id:
            tenant_app = await self.tenant_sharepoint_app_repo.get_by_id(
                app_id=tenant_app_id
            )
            if not tenant_app:
                raise ValueError(f"Tenant app {tenant_app_id} not found")
            access_token, access_token_provider = await self._org_access_token(
                tenant_app
            )
            logger.info(
                "Using %s auth for %s tenant_app %s",
                tenant_app.auth_method,
                purpose,
                tenant_app_id,
            )
            token = SimpleSharePointToken(access_token=access_token)
            return token, None, access_token_provider
        if token_id:
            token = await self.oauth_token_repo.one(id=token_id)
            return _require_sharepoint_token(token), token.id, None
        raise ValueError("Either token_id or tenant_app_id must be provided")

    def _graph_client(
        self,
        token: SharePointTokenProtocol,
        oauth_token_id: Optional[UUID],
        access_token_provider: Optional[AccessTokenProvider],
    ) -> SharePointContentClient:
        return SharePointContentClient(
            base_url=token.base_url,
            api_token=token.access_token,
            token_id=oauth_token_id,
            token_refresh_callback=(
                self.token_refresh_callback if oauth_token_id else None
            ),
            access_token_provider=access_token_provider,
            include_list_item_fields=True,
        )

    async def pull_content(
        self,
        token_id: Optional[UUID] = None,
        tenant_app_id: Optional[UUID] = None,
        integration_knowledge_id: UUID | None = None,
        site_id: Optional[str] = None,
        drive_id: Optional[str] = None,
        folder_id: Optional[str] = None,
        folder_path: Optional[str] = None,
        resource_type: str = "site",
        sync_trigger: str = "manual",
        recovery: str | None = None,
    ) -> str:
        started_at = datetime.now(timezone.utc)
        resolved_integration_knowledge_id: UUID | None = integration_knowledge_id
        # Outside the try: what a failed sync indexed or deleted before the
        # error is committed, so its log records it.
        stats = sync_results.initialize_stats()
        # The token a failure leaves in place; None clears it.
        token_after_failure: str | None = None

        try:
            await self._progress.begin(integration_knowledge_id, "full")
            token, oauth_token_id, access_token_provider = await self._graph_access(
                token_id, tenant_app_id, purpose="full sync"
            )

            integration_knowledge = await self.integration_knowledge_repo.one(
                id=integration_knowledge_id
            )
            resolved_integration_knowledge_id = integration_knowledge.id
            resolved_site_id = site_id or integration_knowledge.site_id
            resolved_drive_id = drive_id or integration_knowledge.drive_id
            binding: SyncStateFields = {}
            if site_id and not getattr(integration_knowledge, "site_id", None):
                integration_knowledge.site_id = site_id
                binding["site_id"] = site_id
            if drive_id:
                integration_knowledge.drive_id = drive_id
                binding["drive_id"] = drive_id
            if resource_type:
                integration_knowledge.resource_type = resource_type
                binding["resource_type"] = resource_type
            if folder_id:
                integration_knowledge.folder_id = folder_id
                binding["folder_id"] = folder_id
            if folder_path:
                integration_knowledge.folder_path = folder_path
                binding["folder_path"] = folder_path
            await self._sync_state.started(integration_knowledge, started_at, **binding)
            await self._invalidate_walk_cache(resolved_integration_knowledge_id)

            delta_baseline, baseline_failure = await self._pull_content(
                token=token,
                oauth_token_id=oauth_token_id,
                integration_knowledge_id=resolved_integration_knowledge_id,
                site_id=resolved_site_id,
                drive_id=resolved_drive_id,
                resource_type=resource_type,
                stats=stats,
                access_token_provider=access_token_provider,
            )
            await self._progress.set_phase("finishing", stats)
            self._schedule_post_commit_change_keys(
                self._index.take_full_sync_citations()
            )
            retries_recorded = await self._settle_failures(
                integration_knowledge,
                stats,
                failed_before=await self._failed_items(
                    resolved_integration_knowledge_id
                ),
                attempted=None,
            )
            summary_stats, forbidden = sync_results.summarize_pass(stats)
            if forbidden:
                raise SyncAccessDenied(
                    summary_stats,
                    forbidden=forbidden,
                    hidden=bool(stats.get("download_not_found")),
                )
            if missing := sync_results.downloads_unavailable(stats):
                raise SyncDownloadsUnavailable(summary_stats, missing=missing)
            if summary_stats.get("failed_items"):
                # A delta never re-emits an unchanged item, so the token may
                # stay only when the next delta pass retries every failure.
                # Otherwise the failure record clears it and the next sync is
                # a full one.
                if retries_recorded and not sync_results.unretryable_failures(stats):
                    token_after_failure = (
                        delta_baseline or integration_knowledge.delta_token
                    )
                raise SyncItemsFailed(summary_stats)
            if not delta_baseline and not integration_knowledge.delta_token:
                raise DeltaBaselineUnavailable(summary_stats, detail=baseline_failure)

            integration_knowledge.last_sync_summary = sync_results.summary_counts(
                summary_stats
            )
            if delta_baseline:
                integration_knowledge.delta_token = delta_baseline
            await self._sync_state.succeeded(
                integration_knowledge, datetime.now(timezone.utc)
            )

            await self._sync_state.add_log(
                SyncLog(
                    integration_knowledge_id=resolved_integration_knowledge_id,
                    sync_type="full",
                    status="success",
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc),
                    metadata=sync_results.sync_metadata(
                        summary_stats,
                        trigger=sync_trigger,
                        recovery=recovery,
                    ),
                )
            )

            return sync_results.format_summary_for_job(summary_stats)

        except Exception as e:
            summary = sync_results.failure_summary(e)
            await self._sync_state.failed(
                resolved_integration_knowledge_id,
                e,
                sync_type="full",
                started_at=started_at,
                summary_counts=sync_results.summary_counts(summary)
                if summary
                else None,
                # What was indexed or deleted before the error is committed with
                # it, so the log records it.
                metadata=sync_results.sync_metadata(
                    summary or sync_results.build_summary_stats(stats),
                    trigger=sync_trigger,
                    recovery=recovery,
                ),
                clear_delta_token=isinstance(e, SyncItemsFailed)
                and token_after_failure is None,
                delta_token=token_after_failure,
            )
            _log_pass_failure("Error in pull_content", e)
            raise
        finally:
            await self._progress.end()

    async def process_delta_changes(
        self,
        token_id: Optional[UUID] = None,
        tenant_app_id: Optional[UUID] = None,
        integration_knowledge_id: UUID | None = None,
        site_id: Optional[str] = None,
        drive_id: Optional[str] = None,
        resource_type: str = "site",
        sync_trigger: str = "webhook",
        record_failure: bool = True,
    ) -> str:
        """Apply the changes since the stored delta token.

        With ``record_failure`` false the pass is a pending one, run by the
        holder of the sync lease for a webhook that arrived during its sync. A
        failure of such a pass is only raised, not written to the knowledge
        row: it must not turn the owning sync's status into an error. When it
        succeeds without having processed anything it also keeps the owning
        sync's summary, which is what the person who started that sync is
        looking at. ``last_sync_attempted_at`` moves on every pass, pending or
        not: it tells a failing integration from an idle one. A full sync run
        as recovery (missing or expired token) is recorded regardless: it was
        attempted, the token it replaces is gone, and the next sync is a full
        one, so its failure is the knowledge's current state.
        """
        started_at = datetime.now(timezone.utc)
        resolved_integration_knowledge_id: UUID | None = integration_knowledge_id
        delegated_to_full_sync = False
        # Outside the try, like the full sync's: changes applied before an
        # error are committed and belong in its log.
        stats = sync_results.initialize_stats()

        try:
            await self._progress.begin(integration_knowledge_id, "delta")
            token, oauth_token_id, access_token_provider = await self._graph_access(
                token_id, tenant_app_id, purpose="delta sync"
            )

            integration_knowledge = await self.integration_knowledge_repo.one(
                id=integration_knowledge_id
            )
            resolved_integration_knowledge_id = integration_knowledge.id
            await self._sync_state.started(integration_knowledge, started_at)
            resolved_site_id = site_id or integration_knowledge.site_id
            resolved_drive_id = drive_id or integration_knowledge.drive_id

            if not integration_knowledge.delta_token:
                logger.warning(
                    f"No delta token found for integration knowledge {integration_knowledge_id}, "
                    "falling back to full sync"
                )
                delegated_to_full_sync = True
                return await self._recover_with_full_sync(
                    token_id=token_id,
                    tenant_app_id=tenant_app_id,
                    integration_knowledge=integration_knowledge,
                    site_id=resolved_site_id,
                    drive_id=resolved_drive_id,
                    resource_type=resource_type,
                    sync_trigger=sync_trigger,
                    recovery="missing_delta_token",
                )

            async with self._graph_client(
                token, oauth_token_id, access_token_provider
            ) as content_client:
                actual_drive_id = resolved_drive_id
                if not actual_drive_id and resolved_site_id:
                    actual_drive_id = await content_client.get_default_drive_id(
                        resolved_site_id
                    )
                if not actual_drive_id:
                    raise ValueError(
                        f"Could not resolve drive ID for site {resolved_site_id}"
                    )

                logger.info(
                    f"Starting delta sync with token: {integration_knowledge.delta_token[:20]}..."
                    if integration_knowledge.delta_token
                    else "No delta token"
                )
                try:
                    changes, new_delta_token = await content_client.get_delta_changes(
                        drive_id=actual_drive_id,
                        delta_token=integration_knowledge.delta_token,
                    )
                except DeltaTokenExpiredException:
                    logger.warning(
                        "Delta token expired (410 Gone) for integration knowledge %s, "
                        "clearing token and falling back to full sync",
                        resolved_integration_knowledge_id,
                    )
                    integration_knowledge.delta_token = None
                    await self.integration_knowledge_repo.update_sync_state(
                        integration_knowledge.id, delta_token=None
                    )
                    delegated_to_full_sync = True
                    return await self._recover_with_full_sync(
                        token_id=token_id,
                        tenant_app_id=tenant_app_id,
                        integration_knowledge=integration_knowledge,
                        site_id=resolved_site_id,
                        drive_id=resolved_drive_id,
                        resource_type=resource_type,
                        sync_trigger=sync_trigger,
                        recovery="delta_token_expired",
                    )
                logger.info(
                    f"Delta query returned {len(changes)} items. New token: {new_delta_token[:20] if new_delta_token else 'None'}..."
                )
                failed_before = await self._failed_items(integration_knowledge.id)
                now = int(self._clock())

                if len(changes) == 0 and not any(
                    item.due(now) for item in failed_before.values()
                ):
                    logger.info(
                        f"Delta query returned 0 changes for integration knowledge {integration_knowledge_id}. "
                        "No updates needed - SharePoint is in sync with database."
                    )

                    if new_delta_token:
                        integration_knowledge.delta_token = new_delta_token

                    summary_stats = sync_results.build_summary_stats(stats)

                    if record_failure:
                        integration_knowledge.last_sync_summary = (
                            sync_results.summary_counts(summary_stats)
                        )
                    await self._sync_state.succeeded(
                        integration_knowledge,
                        datetime.now(timezone.utc),
                        with_summary=record_failure,
                    )

                    logger.info("Delta sync completed: no changes detected")
                    return sync_results.format_summary_for_job(summary_stats)

                logger.info(f"Processing {len(changes)} changed items from delta query")
                (
                    scope_folder_path,
                    folder_scope_path_unresolved,
                ) = await self._refresh_scope_path(
                    content_client, actual_drive_id, changes, integration_knowledge
                )
                delta_pass = _DeltaPass(
                    content_client=content_client,
                    integration_knowledge=integration_knowledge,
                    site_id=resolved_site_id,
                    drive_id=actual_drive_id,
                    stats=stats,
                    change_ids={
                        change_id
                        for change in changes
                        if (change_id := change.get("id"))
                    },
                    scope_folder_path=scope_folder_path,
                    folder_scope_path_unresolved=folder_scope_path_unresolved,
                    known_subfolder_ids=set(),
                    pending_change_keys=[],
                    failed_before=failed_before,
                )
                await self._progress.set_phase("processing", stats)
                await self._place_folder_entries(delta_pass, changes)
                await self._retry_failed_items(delta_pass)
                for item in changes:
                    await self._apply_delta_change(delta_pass, item)

                await self._progress.set_phase("finishing", stats)
                return await self._finish_delta_pass(
                    delta_pass,
                    new_delta_token=new_delta_token,
                    changes_detected=len(changes),
                    record_failure=record_failure,
                    started_at=started_at,
                    sync_trigger=sync_trigger,
                )

        except Exception as e:
            if delegated_to_full_sync:
                # The full sync recorded the failure and its sync log itself.
                raise
            _log_pass_failure("Error processing delta changes", e)
            if not record_failure:
                raise
            summary = sync_results.failure_summary(e)
            await self._sync_state.failed(
                resolved_integration_knowledge_id,
                e,
                sync_type="delta",
                started_at=started_at,
                summary_counts=sync_results.summary_counts(summary)
                if summary
                else None,
                metadata=sync_results.sync_metadata(
                    summary or sync_results.build_summary_stats(stats),
                    trigger=sync_trigger,
                    changes_detected=(
                        e.changes_detected if isinstance(e, SyncItemsFailed) else None
                    ),
                ),
            )
            raise
        finally:
            await self._progress.end()

    async def _recover_with_full_sync(
        self,
        *,
        token_id: Optional[UUID],
        tenant_app_id: Optional[UUID],
        integration_knowledge: "IntegrationKnowledge",
        site_id: Optional[str],
        drive_id: Optional[str],
        resource_type: str,
        sync_trigger: str,
        recovery: str,
    ) -> str:
        """A full sync in place of a delta that has no usable token."""
        return await self.pull_content(
            token_id=token_id,
            tenant_app_id=tenant_app_id,
            integration_knowledge_id=integration_knowledge.id,
            site_id=site_id,
            drive_id=drive_id,
            resource_type=resource_type
            or integration_knowledge.resource_type
            or "site",
            sync_trigger=sync_trigger,
            recovery=recovery,
        )

    async def _refresh_scope_path(
        self,
        content_client: SharePointContentClient,
        drive_id: str,
        changes: list[SharePointItem],
        integration_knowledge: "IntegrationKnowledge",
    ) -> tuple[Optional[str], bool]:
        """The scope folder path this pass classifies against, and whether it is missing.

        Only a folder scope has one; the second value is true when neither Graph
        nor the change set could say where the folder is and nothing is stored.
        """
        scope_folder_path = integration_knowledge.folder_path
        folder_scope_path_unresolved = False
        scope_folder_id = integration_knowledge.folder_id
        if integration_knowledge.selected_item_type == "folder" and scope_folder_id:
            # The stored path goes stale when an ancestor of the scope
            # folder is renamed or moved: Graph emits the ancestor, not
            # the unchanged scope folder, so nothing in the changes
            # carries the new path, and the next change under the folder
            # would be classified against the stale path and deleted as
            # out of scope. Read the current path from Graph each pass.
            # The folder's own delta entry is the second source (Graph
            # orders entries arbitrarily, so a descendant can precede it).
            refreshed_scope_path = await scope_rules.current_scope_folder_path(
                content_client, drive_id, scope_folder_id
            ) or scope_rules.scope_folder_path_from_changes(changes, scope_folder_id)
            if refreshed_scope_path:
                if refreshed_scope_path != scope_folder_path:
                    scope_folder_path = refreshed_scope_path
                    integration_knowledge.folder_path = refreshed_scope_path
                    await self.integration_knowledge_repo.update_sync_state(
                        integration_knowledge.id,
                        folder_path=refreshed_scope_path,
                    )
            elif not scope_folder_path:
                logger.warning(
                    "Could not derive folder_path for delta scope "
                    "(integration_knowledge=%s, folder_id=%s)",
                    integration_knowledge.id,
                    scope_folder_id,
                )
                folder_scope_path_unresolved = True

        return scope_folder_path, folder_scope_path_unresolved

    async def _apply_delta_change(
        self, delta_pass: "_DeltaPass", item: SharePointItem
    ) -> None:
        """Classify one delta entry and apply it: delete, walk a folder or index a file."""
        content_client = delta_pass.content_client
        integration_knowledge = delta_pass.integration_knowledge
        resolved_integration_knowledge_id = integration_knowledge.id
        actual_drive_id = delta_pass.drive_id
        stats = delta_pass.stats
        scope_folder_path = delta_pass.scope_folder_path
        known_subfolder_ids = delta_pass.known_subfolder_ids
        folder_scope = integration_knowledge.selected_item_type == "folder"

        item_name = item.get("name", "")
        item_id = item.get("id")
        is_deleted = has_graph_facet(item, "deleted")
        is_folder = has_graph_facet(item, "folder")
        await self._progress.update(stats)

        # The delta covers the whole drive. Until an item is placed in scope
        # its name is never recorded: what is cleaned up or skipped is named
        # by its item id, and only a file in scope becomes the progress's
        # current file.
        logger.debug(
            "  - Item %s (deleted=%s, folder=%s)", item_id, is_deleted, is_folder
        )

        if not item_id:
            # Cannot be placed in or out of scope; counted only.
            stats["skipped_items"] += 1
            return

        # Graph emits the drive root itself; it carries no parent
        # path, is never indexed, and for a folder scope would be
        # classified out of scope and have the whole drive walked.
        if has_graph_facet(item, "root"):
            return

        # The same goes for every other ancestor of the scope folder: Graph
        # lists the parent chain of a changed item unless the delta request
        # asks it not to, and a renamed ancestor is emitted on its own. An
        # ancestor is above the scope, not out of it, and its subtree holds
        # the scope; nothing of its own is indexed.
        if (
            is_folder
            and not is_deleted
            and folder_scope
            and scope_rules.is_ancestor_of_scope(item, scope_folder_path)
        ):
            return

        # Skip scope check for deleted items — they may lack
        # parentReference data.  The DB delete queries already
        # filter by integration_knowledge_id so they are safe.
        in_scope = (
            is_deleted
            or item_id in known_subfolder_ids
            or scope_rules.is_item_in_folder_scope(
                item,
                integration_knowledge.folder_id,
                scope_folder_path=scope_folder_path,
                known_subfolder_ids=known_subfolder_ids,
                selected_item_type=integration_knowledge.selected_item_type,
            )
        )
        if not in_scope:
            if (
                delta_pass.folder_scope_path_unresolved
                and folder_scope
                and integration_knowledge.folder_id
                and not scope_folder_path
            ):
                logger.warning(
                    "Skipping destructive out-of-scope cleanup for item %s "
                    "because folder_path could not be resolved "
                    "for integration_knowledge %s",
                    item_id,
                    resolved_integration_knowledge_id,
                )
                sync_results.count_skip(
                    stats, skipped_by_code(item_id, "scope_path_unavailable")
                )
                sync_results.keep_recorded(stats, item_id)
                return

            # Without a path the entry is out of scope only because its parent
            # is not in this change set, which says nothing about where it is.
            if folder_scope and not scope_rules.parent_path(item):
                located = await self._place_unplaced_entry(
                    delta_pass, item, is_folder=is_folder
                )
                if located is None or (
                    is_folder
                    and scope_rules.is_ancestor_of_scope(located, scope_folder_path)
                ):
                    return
                in_scope = scope_rules.is_item_in_folder_scope(
                    located,
                    integration_knowledge.folder_id,
                    scope_folder_path=scope_folder_path,
                    known_subfolder_ids=known_subfolder_ids,
                    selected_item_type="folder",
                )

        if not in_scope:
            logger.debug("  - Skipping item %s: not in folder scope", item_id)
            await self._index.remove(
                item_id=item_id,
                item_name=item_id,
                integration_knowledge=integration_knowledge,
                integration_knowledge_id=resolved_integration_knowledge_id,
                stats=stats,
                reason="out-of-scope",
            )
            # A folder that left scope still exists in SharePoint, but Graph
            # does not re-emit its (unchanged) children — deleting only the
            # folder id would orphan every descendant blob. Enumerate the
            # folder's current descendants and remove them too. Only a
            # folder scope ever indexes descendants; a file scope has
            # nothing under any folder.
            if is_folder and folder_scope:
                await self._clean_folder_left_scope(delta_pass, item)
            return

        if is_deleted:
            # Never placed in scope (see above), so named by its id; a removed
            # document keeps its own title.
            await self._index.remove(
                item_id=item_id,
                item_name=item_id,
                integration_knowledge=integration_knowledge,
                integration_knowledge_id=resolved_integration_knowledge_id,
                stats=stats,
                reason="removed",
            )
            return

        if is_folder:
            stats["folders_processed"] += 1
            if folder_scope and item_id != integration_knowledge.folder_id:
                await self._walk_folder_in_scope(delta_pass, item)
            return

        await self._progress.update(stats, current=item_name)
        await self._index.index_file(
            client=content_client,
            drive_id=actual_drive_id,
            item=item,
            integration_knowledge=integration_knowledge,
            stats=stats,
            pending_change_keys=delta_pass.pending_change_keys,
        )

    async def _place_folder_entries(
        self, delta_pass: "_DeltaPass", changes: list[SharePointItem]
    ) -> None:
        """Place the change set's folders against the scope before any entry is applied.

        Graph orders a change set arbitrarily and need not give a parent path
        in delta, so a folder is in scope when its parent is the scope folder
        or an in-scope folder anywhere in the set, not only one seen earlier. A
        folder that this leaves unplaced and that has no path of its own is
        asked about once; its answer decides it and the folders under it.
        """
        integration_knowledge = delta_pass.integration_knowledge
        scope_folder_id = integration_knowledge.folder_id
        if integration_knowledge.selected_item_type != "folder" or not scope_folder_id:
            return
        folders = {
            folder_id: entry
            for entry in changes
            if (folder_id := entry.get("id"))
            and has_graph_facet(entry, "folder")
            and not has_graph_facet(entry, "deleted")
            and not has_graph_facet(entry, "root")
        }
        children: dict[str, list[str]] = {}
        for folder_id, entry in folders.items():
            if parent_id := entry.get("parentReference", {}).get("id"):
                children.setdefault(parent_id, []).append(folder_id)

        in_scope = delta_pass.known_subfolder_ids

        def admit(folder_id: str) -> None:
            pending = [folder_id]
            while pending:
                current = pending.pop()
                if current not in in_scope:
                    in_scope.add(current)
                    pending.extend(children.get(current, ()))

        admit(scope_folder_id)
        for folder_id, entry in folders.items():
            if scope_rules.is_item_in_folder_scope(
                entry,
                scope_folder_id,
                scope_folder_path=delta_pass.scope_folder_path,
                selected_item_type="folder",
            ):
                admit(folder_id)

        if not delta_pass.scope_folder_path:
            return
        for folder_id, entry in folders.items():
            if folder_id in in_scope or scope_rules.parent_path(entry):
                continue
            located = await self._locate_entry(delta_pass, entry, kind="folder")
            delta_pass.placements[folder_id] = located
            if located is not None and scope_rules.is_item_in_folder_scope(
                located,
                scope_folder_id,
                scope_folder_path=delta_pass.scope_folder_path,
                known_subfolder_ids=in_scope,
                selected_item_type="folder",
            ):
                admit(folder_id)

    async def _place_unplaced_entry(
        self, delta_pass: "_DeltaPass", item: SharePointItem, *, is_folder: bool
    ) -> Optional[SharePointItem]:
        """Where an entry without a path is, when that decides anything; else ``None``.

        Folders were placed before the entries were applied. New files need
        placement too: skipping an unindexed file would advance past its only
        delta event and leave it missing until a full sync.
        """
        item_id = item.get("id", "")
        if is_folder:
            return delta_pass.placements.get(item_id)
        return await self._locate_entry(delta_pass, item, kind="file")

    async def _locate_entry(
        self, delta_pass: "_DeltaPass", item: SharePointItem, *, kind: str
    ) -> Optional[SharePointItem]:
        """The item as Graph has it now, with its path; ``None`` when Graph cannot say.

        Either way nothing of it is deleted. An answer about the item (403,
        404, 410) or one without a path keeps it for a full sync to reconcile
        and lets the pass move on; any other failure fails the pass, which
        keeps its token and is replayed.
        """
        item_id = item.get("id", "")
        item_name = item_id  # Membership is unknown; do not disclose its name.
        stats = delta_pass.stats
        try:
            located = cast(
                SharePointItem,
                await delta_pass.content_client.get_file_metadata(
                    drive_id=delta_pass.drive_id, item_id=item_id
                ),
            )
        except Exception as exc:
            if (
                not isinstance(exc, aiohttp.ClientResponseError)
                or exc.status not in ITEM_LEVEL_HTTP_STATUSES
            ):
                logger.warning(
                    "Could not read where %s %s (%s) is: %s",
                    kind,
                    item_name,
                    item_id,
                    exc,
                )
                sync_results.count_failure(
                    stats,
                    skipped(
                        item_name,
                        f"Could not confirm where the {kind} is in SharePoint: "
                        + user_visible_error(exc),
                    ),
                    item_id=item_id,
                )
                return None
            unplaced = f" ({user_visible_error(exc)})"
        else:
            if scope_rules.parent_path(located):
                return located
            unplaced = ""
        logger.warning(
            "Keeping %s %s (%s): Graph could not place it against the scope",
            kind,
            item_name,
            item_id,
        )
        sync_results.count_skip(
            stats,
            skipped(
                item_name,
                f"Could not confirm where the {kind} is in SharePoint"
                f"{unplaced}; kept until the next full sync",
            ),
        )
        sync_results.keep_recorded(stats, item_id)
        return None

    async def _pass_indexed_ids(
        self, delta_pass: "_DeltaPass", item_name: str
    ) -> set[str] | None:
        """The indexed item ids, read once per pass; ``None`` when the read failed.

        The failure is counted against the entry that needed them, so the pass
        keeps its token and is replayed.
        """
        if delta_pass.indexed_ids is None:
            try:
                indexed = await self._index.list_items(
                    delta_pass.integration_knowledge.id
                )
            except Exception as exc:
                logger.warning(
                    "Could not read the indexed SharePoint items: %s",
                    exc,
                    exc_info=True,
                )
                sync_results.count_failure(
                    delta_pass.stats,
                    skipped(
                        item_name,
                        "Could not read the indexed documents: "
                        + user_visible_error(exc),
                    ),
                )
                return None
            delta_pass.indexed_ids = {item_id for _, item_id in indexed}
        return delta_pass.indexed_ids

    def _savepoint(self) -> AbstractAsyncContextManager[object]:
        # Unit tests hand the service a stand-in without savepoints.
        session = cast(object, self.session)
        if isinstance(session, SqlAlchemyAsyncSession):
            return session.begin_nested()
        return nullcontext()

    async def _failed_items(self, knowledge_id: UUID) -> dict[str, FailedItem]:
        """The items earlier passes could not finish; empty when unreadable."""
        try:
            async with self._savepoint():
                stored = await self.integration_knowledge_repo.get_sync_failed_items(
                    knowledge_id
                )
        except Exception as exc:
            logger.warning(
                "Could not read the failed SharePoint items of %s: %s",
                knowledge_id,
                exc,
            )
            return {}
        return decode_failed_items(stored)

    async def _retry_failed_items(self, delta_pass: "_DeltaPass") -> None:
        """Apply what Graph says now about items earlier passes could not finish.

        A delta never re-emits an unchanged item, so a failure a full sync
        recorded is only retried here. Items the change set carries are
        applied from it instead, and a set-aside item waits out its cool-off.
        Gone (404, 410) is removed, refused (403) counts as a refused
        download, anything else fails the item again.
        """
        now = int(self._clock())
        for item_id, failed in delta_pass.failed_before.items():
            if item_id in delta_pass.change_ids or not failed.due(now):
                continue
            delta_pass.retried_ids.add(item_id)
            try:
                current = cast(
                    SharePointItem,
                    await delta_pass.content_client.get_file_metadata(
                        drive_id=delta_pass.drive_id, item_id=item_id
                    ),
                )
            except aiohttp.ClientResponseError as exc:
                if exc.status in (404, 410):
                    await self._index.remove(
                        item_id=item_id,
                        item_name=item_id,
                        integration_knowledge=delta_pass.integration_knowledge,
                        integration_knowledge_id=delta_pass.integration_knowledge.id,
                        stats=delta_pass.stats,
                        reason="removed",
                    )
                elif exc.status == 403:
                    sync_results.count_refused_download(
                        delta_pass.stats, item_id, download=False
                    )
                    sync_results.count_skip(
                        delta_pass.stats, error_skipped(item_id, exc)
                    )
                else:
                    self._retry_failed(delta_pass, item_id, exc)
                continue
            except Exception as exc:
                self._retry_failed(delta_pass, item_id, exc)
                continue
            await self._apply_delta_change(delta_pass, current)

    @staticmethod
    def _retry_failed(delta_pass: "_DeltaPass", item_id: str, exc: Exception) -> None:
        detail = error_skipped(item_id, exc)
        sync_results.count_attempt(delta_pass.stats)
        sync_results.count_failure(delta_pass.stats, detail, item_id=item_id)
        sync_results.item_failed_in_a_row(delta_pass.stats, detail)

    async def _settle_failures(
        self,
        integration_knowledge: "IntegrationKnowledge",
        stats: SyncStats,
        *,
        failed_before: dict[str, FailedItem],
        attempted: set[str] | None,
    ) -> bool:
        """Record this pass's failures per item; a set-aside item's are skips.

        How failures count and when an item is set aside is ``FailedItem``'s;
        a set-aside item's failure lets the pass advance past it. What the
        record held and this pass tried without failing is forgotten;
        ``attempted`` None means the pass tried every item (a full sync). The
        record is written in the pass's transaction. A refusal confirming one
        at least ``COUNT_INTERVAL_SECONDS`` earlier removes the indexed copy,
        unless the pass shows the identity lost access. True when every
        failure naming an item is recorded.
        """
        knowledge_id = integration_knowledge.id
        now = int(self._clock())
        # An outage fails the pass and keeps the token; nobody's count moves.
        systemic = sync_results.failures_look_systemic(stats)
        failed_now: dict[str, FailedItem] = {}
        for item_id in sync_results.failed_item_ids(stats):
            previous = failed_before.get(item_id)
            if systemic:
                failed_now[item_id] = previous or FailedItem.uncounted()
                continue
            failed = (
                previous.after_failure(now)
                if previous
                else FailedItem.first_failure(now)
            )
            failed_now[item_id] = failed
            if failed.set_aside_at is not None:
                sync_results.set_aside(stats, item_id, attempts=failed.counted)
        refused = stats.get("refused_downloads", {})
        if not sync_results.refused_access(stats):
            confirmed: dict[str, str] = {}
            for item_id, item_name in refused.items():
                refusal, again = (
                    failed_before.get(item_id) or FailedItem.uncounted()
                ).after_refusal(now)
                if again:
                    confirmed[item_id] = item_name
                else:
                    failed_now[item_id] = refusal
            removed = await self._index.remove_refused(
                integration_knowledge, stats, confirmed
            )
            refused = {
                item_id: name
                for item_id, name in refused.items()
                if item_id not in removed
            }
        undecided = stats.get("undecided_items", set[str]())
        kept = {
            item_id: item
            for item_id, item in failed_before.items()
            if item_id in failed_now
            or item_id in refused
            or item_id in undecided
            or (attempted is not None and item_id not in attempted)
        }
        recorded = len(kept) + len(failed_now.keys() - kept.keys()) <= MAX_FAILED_ITEMS
        if recorded:
            kept.update(failed_now)
        else:
            logger.warning(
                "Not recording %d failed SharePoint items of %s: above the limit of %d",
                len(failed_now.keys() - kept.keys()),
                knowledge_id,
                MAX_FAILED_ITEMS,
            )
            kept.update(
                (item_id, item)
                for item_id, item in failed_now.items()
                if item_id in kept
            )
        if kept == failed_before:
            return recorded
        try:
            async with self._savepoint():
                await self.integration_knowledge_repo.update_sync_state(
                    knowledge_id, sync_failed_items=encode_failed_items(kept)
                )
        except Exception as exc:
            logger.warning(
                "Could not record the failed SharePoint items of %s: %s",
                knowledge_id,
                exc,
            )
            return False
        return recorded

    async def _invalidate_walk_cache(self, knowledge_id: UUID) -> None:
        """Have the next delta walk every folder again; see ``WalkGenerations``."""
        if self._walk_generations is None:
            return
        try:
            await self._walk_generations.advance(knowledge_id)
        except Exception as exc:
            logger.warning(
                "Could not invalidate the folder walk cache of %s: %s",
                knowledge_id,
                exc,
            )

    async def _walk_cache_suffix(self, delta_pass: "_DeltaPass") -> Optional[str]:
        if not delta_pass.walk_cache_suffix_read:
            delta_pass.walk_cache_suffix_read = True
            if self._walk_generations is None:
                delta_pass.walk_cache_suffix = ""
            else:
                try:
                    generation = await self._walk_generations.current(
                        delta_pass.integration_knowledge.id
                    )
                except Exception as exc:
                    logger.warning("Could not read the walk cache generation: %s", exc)
                else:
                    delta_pass.walk_cache_suffix = f"@{generation}"
        return delta_pass.walk_cache_suffix

    async def _walk_folder_in_scope(
        self, delta_pass: "_DeltaPass", item: SharePointItem
    ) -> None:
        """Index what an in-scope folder entry brought in, unless it was walked there before.

        The entry does not say whether the folder moved, so its parent and name
        are kept once a walk completed without failures, post-commit like a
        file's ChangeKey. A folder re-emitted under the same parent and name (a
        permission change, a replayed pass) has its files indexed already,
        unless a full sync ran since: it may have removed them as orphans while
        the folder was elsewhere, so the key carries the walk generation. A
        rename or move is walked: Graph emits no entry for the descendants,
        whose titles and links the walk refreshes.
        """
        integration_knowledge = delta_pass.integration_knowledge
        item_id = item.get("id", "")
        item_name = item.get("name", "")
        stats = delta_pass.stats
        parent_id = item.get("parentReference", {}).get("id")
        suffix = await self._walk_cache_suffix(delta_pass)
        name_key = hashlib.sha256(item_name.encode("utf-8")).hexdigest()[:16]
        location_key = (
            f"folder-under:{parent_id}:{name_key}{suffix}"
            if parent_id and suffix is not None
            else None
        )
        if location_key and self._index.change_key_service:
            try:
                walked_here = not await self._index.change_key_service.should_process(
                    integration_knowledge_id=integration_knowledge.id,
                    item_id=item_id,
                    change_key=location_key,
                )
            except Exception as exc:
                logger.warning("Could not read the walk cache for %s: %s", item_id, exc)
                walked_here = False
            if walked_here:
                return

        indexed_ids = await self._pass_indexed_ids(delta_pass, item_name)
        if indexed_ids is None:
            return
        failed_before = stats.get("failed_items", 0)
        await self._index_folder_subtree_entering_scope(
            content_client=delta_pass.content_client,
            resource_type=integration_knowledge.resource_type or "site",
            site_id=delta_pass.site_id,
            drive_id=delta_pass.drive_id,
            folder_id=item_id,
            folder_name=item_name,
            integration_knowledge=integration_knowledge,
            stats=stats,
            pending_change_keys=delta_pass.pending_change_keys,
            change_ids=delta_pass.change_ids,
            indexed_ids=indexed_ids,
        )
        if location_key and stats.get("failed_items", 0) == failed_before:
            delta_pass.pending_change_keys.append(
                (integration_knowledge.id, item_id, location_key)
            )

    async def _clean_folder_left_scope(
        self, delta_pass: "_DeltaPass", item: SharePointItem
    ) -> None:
        """Remove what was indexed under a folder entry that is out of scope.

        Only the walk can say what lies under the folder now; it is skipped
        when nothing can be there: Graph reports the folder empty or nothing
        is indexed at all.
        """
        folder = item.get("folder")
        if isinstance(folder, dict) and folder.get("childCount") == 0:
            return
        item_name = item.get("id", "")  # Outside this source; keep its name private.
        indexed_ids = await self._pass_indexed_ids(delta_pass, item_name)
        if not indexed_ids:
            return
        integration_knowledge = delta_pass.integration_knowledge
        await self._reconciliation.remove_subtree(
            content_client=delta_pass.content_client,
            resource_type=integration_knowledge.resource_type or "site",
            site_id=delta_pass.site_id,
            drive_id=delta_pass.drive_id,
            folder_id=item.get("id", ""),
            folder_name=item_name,
            integration_knowledge=integration_knowledge,
            integration_knowledge_id=integration_knowledge.id,
            stats=delta_pass.stats,
            scope_folder_path=delta_pass.scope_folder_path,
            known_subfolder_ids=delta_pass.known_subfolder_ids,
            indexed_ids=indexed_ids,
        )

    async def _finish_delta_pass(
        self,
        delta_pass: "_DeltaPass",
        *,
        new_delta_token: Optional[str],
        changes_detected: int,
        record_failure: bool,
        started_at: datetime,
        sync_trigger: str,
    ) -> str:
        """Decide the pass's outcome, persist it and write its sync log."""
        integration_knowledge = delta_pass.integration_knowledge
        resolved_integration_knowledge_id = integration_knowledge.id
        stats = delta_pass.stats
        pending_change_keys = delta_pass.pending_change_keys

        await self._settle_failures(
            integration_knowledge,
            stats,
            failed_before=delta_pass.failed_before,
            attempted=delta_pass.change_ids | delta_pass.retried_ids,
        )
        summary_stats, forbidden = sync_results.summarize_pass(stats)
        if forbidden or summary_stats.get("failed_items"):
            # Keep the token: Graph never re-emits an item once a pass
            # moved past it, so the next pass replays this one. Items
            # indexed now are skipped as unchanged through the
            # post-commit ChangeKey cache; the scope path refreshed
            # above was persisted so the replay classifies as this pass did.
            self._schedule_post_commit_change_keys(pending_change_keys)
            if forbidden:
                raise SyncAccessDenied(
                    summary_stats,
                    forbidden=forbidden,
                    hidden=bool(stats.get("download_not_found")),
                    changes_detected=changes_detected,
                )
            if missing := sync_results.downloads_unavailable(stats):
                raise SyncDownloadsUnavailable(
                    summary_stats, missing=missing, changes_detected=changes_detected
                )
            raise SyncItemsFailed(summary_stats, changes_detected=changes_detected)

        integration_knowledge.delta_token = new_delta_token
        replace_summary = record_failure or sync_results.delta_worth_logging(
            summary_stats
        )
        if replace_summary:
            integration_knowledge.last_sync_summary = sync_results.summary_counts(
                summary_stats
            )
        logger.info(f"Delta sync completed: {summary_stats}")

        await self._sync_state.succeeded(
            integration_knowledge,
            datetime.now(timezone.utc),
            with_summary=replace_summary,
        )

        self._schedule_post_commit_change_keys(pending_change_keys)

        logger.info(
            f"Processed {changes_detected} delta changes for integration knowledge {resolved_integration_knowledge_id}"
        )

        if sync_results.delta_worth_logging(summary_stats):
            await self._sync_state.add_log(
                SyncLog(
                    integration_knowledge_id=resolved_integration_knowledge_id,
                    sync_type="delta",
                    status="success",
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc),
                    metadata=sync_results.sync_metadata(
                        summary_stats,
                        trigger=sync_trigger,
                        changes_detected=changes_detected,
                    ),
                )
            )
        else:
            logger.info(
                f"Skipping sync log creation for integration knowledge {integration_knowledge.id}: "
                "no files processed or deleted"
            )

        return sync_results.format_summary_for_job(summary_stats)

    async def _pull_content(
        self,
        token: SharePointTokenProtocol,
        oauth_token_id: Optional[UUID],
        integration_knowledge_id: UUID,
        site_id: Optional[str],
        drive_id: Optional[str],
        resource_type: str,
        stats: SyncStats,
        access_token_provider: Optional[AccessTokenProvider] = None,
    ) -> tuple[str | None, str | None]:
        """Enumerate and index the scope; returns the delta baseline minted for it.

        The baseline is minted before the first listing: a change made while a
        folder is being enumerated is then replayed by the first delta instead
        of lost until the item changes again (the replay is idempotent through
        the content hash and the ChangeKey cache). The caller persists it with
        the success write, or with a failure whose items the next delta pass
        retries. The baseline is ``None`` when the knowledge already has a
        token or the mint failed; the second value says why it failed.

        Args:
            token: SharePoint token for authentication (SharePointToken or SimpleSharePointToken)
            oauth_token_id: OAuth token ID for user_oauth integrations, None for tenant_app
            integration_knowledge_id: ID of the integration knowledge object
            site_id: The SharePoint site ID (required for SharePoint, None for OneDrive)
            drive_id: Direct drive ID (required for OneDrive, optional for SharePoint)
            resource_type: 'site' for SharePoint, 'onedrive' for OneDrive
        """
        integration_knowledge = await self.integration_knowledge_repo.one(
            id=integration_knowledge_id
        )
        delta_baseline: str | None = None
        baseline_failure: str | None = None

        try:
            site_id_value = site_id
            if resource_type != "onedrive":
                site_id_value = require_text(site_id_value, "site_id")

            async with self._graph_client(
                token, oauth_token_id, access_token_provider
            ) as content_client:
                actual_drive_id = drive_id
                if not actual_drive_id and site_id_value:
                    actual_drive_id = await content_client.get_default_drive_id(
                        site_id_value
                    )

                if not actual_drive_id:
                    raise ValueError(
                        "Could not determine drive_id - need either drive_id or site_id"
                    )

                if not integration_knowledge.delta_token:
                    (
                        delta_baseline,
                        baseline_failure,
                    ) = await self._mint_delta_baseline(
                        content_client, actual_drive_id, integration_knowledge_id
                    )

                if integration_knowledge.folder_id:
                    await self._pull_selected_item(
                        content_client=content_client,
                        drive_id=actual_drive_id,
                        site_id=site_id_value,
                        resource_type=resource_type,
                        integration_knowledge=integration_knowledge,
                        stats=stats,
                    )
                else:
                    await self._pull_site_root(
                        content_client=content_client,
                        drive_id=actual_drive_id,
                        site_id=site_id_value,
                        resource_type=resource_type,
                        integration_knowledge=integration_knowledge,
                        stats=stats,
                    )

        except Exception as e:
            logger.error(f"Error processing document {site_id}: {e}", exc_info=True)
            raise

        return delta_baseline, baseline_failure

    async def _pull_selected_item(
        self,
        *,
        content_client: SharePointContentClient,
        drive_id: str,
        site_id: Optional[str],
        resource_type: str,
        integration_knowledge: "IntegrationKnowledge",
        stats: SyncStats,
    ) -> None:
        """Full sync of a selected folder (with reconciliation) or a single file."""
        folder_id_value = require_text(integration_knowledge.folder_id, "folder_id")
        item_info = await content_client.get_file_metadata(
            drive_id=drive_id,
            item_id=folder_id_value,
        )
        is_folder = item_info.get("folder") is not None
        item_name = item_info.get("name", "")

        if is_folder:
            logger.info(
                f"Processing folder '{item_name}' (ID: {folder_id_value}) "
                f"for integration knowledge {integration_knowledge.id}"
            )
            integration_knowledge.selected_item_type = "folder"
            # A full sync runs on delta recovery (expired/missing
            # token). If the selected folder was renamed or moved
            # while the token was invalid, the stored folder_path is
            # now stale and is never re-emitted as a delta change.
            # The next delta would then misclassify valid nested
            # descendants as out-of-scope and delete their blobs.
            # Refresh the scope path from the freshly fetched folder
            # metadata, mirroring the delta-path refresh.
            refreshed_folder_path = scope_rules.folder_path_from_item(
                cast(SharePointItem, item_info)
            )
            scope: SyncStateFields = {"selected_item_type": "folder"}
            if refreshed_folder_path:
                integration_knowledge.folder_path = refreshed_folder_path
                scope["folder_path"] = refreshed_folder_path
            await self.integration_knowledge_repo.update_sync_state(
                integration_knowledge.id, **scope
            )
            processed_items: set[str] = set()
            await self._fetch_and_process_content(
                site_id=site_id,
                drive_id=drive_id,
                resource_type=resource_type,
                client=content_client,
                integration_knowledge=integration_knowledge,
                folder_id=folder_id_value,
                processed_items=processed_items,
                stats=stats,
            )
            await self._progress.set_phase("finishing", stats)
            await self._reconciliation.reconcile(
                client=content_client,
                integration_knowledge=integration_knowledge,
                resource_type=resource_type,
                site_id=site_id,
                drive_id=drive_id,
                folder_id=folder_id_value,
                stats=stats,
            )
            return
        else:
            logger.info(
                f"Processing single file '{item_name}' (ID: {folder_id_value}) "
                f"for integration knowledge {integration_knowledge.id}"
            )
            integration_knowledge.selected_item_type = "file"
            await self.integration_knowledge_repo.update_sync_state(
                integration_knowledge.id, selected_item_type="file"
            )
            self._progress.add_total(1)
            await self._progress.set_phase("processing", stats)
            await self._progress.update(stats, current=item_name)

            await self._index.index_file(
                client=content_client,
                drive_id=drive_id,
                item=cast(SharePointItem, {**item_info, "id": folder_id_value}),
                integration_knowledge=integration_knowledge,
                stats=stats,
            )
            return

    async def _pull_site_root(
        self,
        *,
        content_client: SharePointContentClient,
        drive_id: str,
        site_id: Optional[str],
        resource_type: str,
        integration_knowledge: "IntegrationKnowledge",
        stats: SyncStats,
    ) -> None:
        """Full sync of a whole drive, plus the site pages of a SharePoint site."""
        integration_knowledge.selected_item_type = "site_root"
        await self.integration_knowledge_repo.update_sync_state(
            integration_knowledge.id, selected_item_type="site_root"
        )

        # Enumerate the drive the knowledge is bound to; asking Graph for
        # the site's default drive again would silently diverge from the
        # drive the delta token and reconciliation operate on.
        data = await content_client.get_drive_root_children(drive_id)

        if data:
            await self._process_documents(
                documents=data,
                client=content_client,
                integration_knowledge=integration_knowledge,
                resource_type=resource_type,
                stats=stats,
            )

        if resource_type != "onedrive" and site_id:
            pages = await content_client.get_site_pages(
                site_id=require_text(site_id, "site_id")
            )
            if data := pages.get("value", []):
                await self._process_pages(
                    pages=data,
                    client=content_client,
                    integration_knowledge=integration_knowledge,
                    stats=stats,
                )

        await self._progress.set_phase("finishing", stats)
        await self._reconciliation.reconcile(
            client=content_client,
            integration_knowledge=integration_knowledge,
            resource_type=resource_type,
            site_id=site_id,
            drive_id=drive_id,
            folder_id=None,
            stats=stats,
        )

    @staticmethod
    async def _mint_delta_baseline(
        content_client: SharePointContentClient,
        drive_id: str,
        integration_knowledge_id: UUID,
    ) -> tuple[str | None, str | None]:
        """A delta token for the drive as it is now, or ``None`` and why not."""
        try:
            delta_token = await content_client.initialize_delta_token(drive_id)
        except Exception as e:
            logger.warning(
                "Failed to initialize delta token for integration knowledge %s: %s",
                integration_knowledge_id,
                e,
            )
            return None, user_visible_error(e)
        if not delta_token:
            return None, "Graph returned no delta link"
        logger.info(
            "Initialized delta token for integration knowledge %s",
            integration_knowledge_id,
        )
        return delta_token, None

    async def _process_documents(
        self,
        documents: list[SharePointItem],
        client: SharePointContentClient,
        integration_knowledge: "IntegrationKnowledge",
        resource_type: str,
        stats: SyncStats,
    ):
        self._progress.add_total(self._file_count(documents))
        await self._progress.set_phase("processing", stats)
        for document in documents:
            await self._progress.update(
                stats,
                current=None if document.get("folder") else document.get("name"),
            )
            drive_id = document.get("parentReference", {}).get("driveId")
            site_id = document.get("parentReference", {}).get("siteId")
            item_id = document.get("id")
            if not drive_id or not item_id:
                continue
            if document.get("folder", {}):
                stats["folders_processed"] += 1
                # Recursively process all items in the folder
                processed_items: set[str] = set()
                await self._fetch_and_process_content(
                    site_id=site_id,
                    drive_id=drive_id,
                    resource_type=resource_type,
                    client=client,
                    integration_knowledge=integration_knowledge,
                    folder_id=item_id,
                    processed_items=processed_items,
                    stats=stats,
                )
            else:
                await self._index.index_file(
                    client=client,
                    drive_id=drive_id,
                    item=document,
                    integration_knowledge=integration_knowledge,
                    stats=stats,
                )

    async def _process_pages(
        self,
        pages: list[SharePointItem],
        client: SharePointContentClient,
        integration_knowledge: "IntegrationKnowledge",
        stats: SyncStats,
    ):
        self._progress.add_total(self._file_count(pages))
        await self._progress.set_phase("processing", stats)
        for page in pages:
            site_id = page.get("parentReference", {}).get("siteId")
            page_id = page.get("id")
            if not site_id or not page_id:
                continue
            page_name = (
                page.get("name", "") or page.get("title", "") or f"Page {page_id}"
            )
            await self._progress.update(stats, current=page_name)
            try:
                content = await client.get_page_content(
                    site_id=site_id, page_id=page_id
                )
                page_text = ""
                if content:
                    page_text = extract_text_from_canvas_layout(content)
                    if not page_text:
                        page_text = content.get("description", "")
                if not content or not page_text.strip():
                    sync_results.count_skip(
                        stats, skipped_by_code(page_name, "empty_content")
                    )
                    continue
                outcome = await self._index.upsert(
                    title=content.get("title", ""),
                    text=page_text,
                    url=content.get("webUrl", ""),
                    integration_knowledge=integration_knowledge,
                    sharepoint_item_id=page_id,
                    stats=stats,
                    item_name=page_name,
                )
                sync_results.count_outcome(stats, outcome, page_name, page=True)
            except Exception as e:
                logger.error(
                    f"Error processing site page {page_name}: {e}", exc_info=True
                )
                sync_results.count_failure(stats, error_skipped(page_name, e))

    async def _index_folder_subtree_entering_scope(
        self,
        *,
        content_client: SharePointContentClient,
        resource_type: str,
        site_id: Optional[str],
        drive_id: str,
        folder_id: str,
        folder_name: str,
        integration_knowledge: "IntegrationKnowledge",
        stats: SyncStats,
        pending_change_keys: list[tuple[UUID, str, str]],
        change_ids: set[str],
        indexed_ids: set[str],
    ) -> None:
        """Index the files of a folder entry that may have entered the selected scope.

        Graph re-emits only the moved folder, not its unchanged children, so a
        folder dragged into scope would otherwise never get its files indexed.
        An in-scope folder entry not walked under its parent and name before
        takes this path because the entry does not say whether it moved;
        children that arrive as their own entries in this change set are left
        alone, and already indexed ones only get their title and link
        refreshed. ``indexed_ids`` is the pass's set; files indexed here are
        added so a nested folder entering scope does not download them again.
        """
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
                "Could not list folder %s (%s) entering scope; the next pass "
                "replays the folder: %s",
                folder_name,
                folder_id,
                exc,
                exc_info=True,
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
            if not descendant_id or descendant_id in change_ids:
                continue
            if descendant_id in indexed_ids:
                # The folder was renamed or moved: the file's link changed.
                await self._index.refresh_citation(
                    descendant,
                    descendant_id,
                    integration_knowledge.id,
                    pending_change_keys,
                )
                continue
            await self._progress.update(stats, current=descendant.get("name"))
            await self._index.index_file(
                client=content_client,
                drive_id=drive_id,
                item=descendant,
                integration_knowledge=integration_knowledge,
                stats=stats,
                pending_change_keys=pending_change_keys,
            )
            indexed_ids.add(descendant_id)

    def _schedule_post_commit_change_keys(
        self, pending: list[tuple[UUID, str, str]]
    ) -> None:
        """Write the Redis ChangeKey cache only after the DB transaction commits.

        The worker wrapper commits on a soft failure: ``set_status_on_exception``
        turns an ``Exception`` from the sync into a FAILED job and the
        transaction still commits, so info_blobs written before the error stay
        (content_hash makes the re-run idempotent). The transaction is only
        rolled back on lease loss or worker shutdown (``CancelledError``, which
        bypasses the per-item ``except``) and when the commit itself fails.
        Writing the ChangeKey inline would let Redis claim such an item is
        processed while its info_blob was rolled back, skipping it until the
        7-day TTL or a 410 resync. Deferring to ``after_commit`` means a
        rolled-back sync simply re-processes the item next time — the safe
        direction.

        The flush is a deliberate fire-and-forget task (a sync ``after_commit`` event
        cannot await). If the worker is killed in the tiny window between commit and
        flush the ChangeKey is lost, but that fails in the same safe direction: the
        next sync re-downloads the item and the content_hash check skips the (costly)
        re-embed, so the only cost is a redundant download. Not worth blocking the
        event loop with a synchronous Redis write to close it.
        """
        if not pending or not self._index.change_key_service:
            return
        # Skipping is the safe direction: the item re-processes next sync.
        if not self._after_transaction(
            partial(self._flush_change_keys, pending), on_rollback=False
        ):
            logger.warning("Could not register post-commit ChangeKey flush")

    def _after_transaction(
        self, callback: Callable[[], Coroutine[Any, Any, None]], *, on_rollback: bool
    ) -> bool:
        """Run ``callback`` once the session's outermost transaction commits, or
        also once it rolls back with ``on_rollback``; False when there is no
        transaction to wait for.

        Savepoints end inside that transaction (info blob publication uses
        them, also in a pending delta pass after a sync) and do not count. A
        non-ORM session (unit tests) and a session without an active
        transaction (a failed top-level flush has already rolled it back and
        sent its only rollback event) have nothing to wait for.
        """
        sync_session = getattr(self.session, "sync_session", None)
        if not isinstance(sync_session, Session):
            return False
        transaction = sync_session.get_transaction()
        if transaction is None or not transaction.is_active:
            return False

        def schedule() -> None:
            task = asyncio.get_running_loop().create_task(callback())
            self._post_transaction_tasks.add(task)
            task.add_done_callback(self._post_transaction_tasks.discard)

        try:
            after_outer_transaction(
                sync_session,
                on_commit=callback,
                on_rollback=schedule if on_rollback else None,
                tasks=self._post_transaction_tasks,
            )
        except ValueError:
            # Inside a savepoint: nothing to wait for that the caller can see.
            return False
        return True

    async def _flush_change_keys(self, pending: list[tuple[UUID, str, str]]) -> None:
        if not self._index.change_key_service:
            return
        for integration_knowledge_id, item_id, change_key in pending:
            try:
                await self._index.change_key_service.update_change_key(
                    integration_knowledge_id=integration_knowledge_id,
                    item_id=item_id,
                    change_key=change_key,
                )
            except Exception as exc:
                logger.warning(
                    "Deferred ChangeKey write failed for item %s: %s", item_id, exc
                )

    async def _fetch_and_process_content(
        self,
        site_id: Optional[str],
        drive_id: Optional[str],
        resource_type: str,
        integration_knowledge: "IntegrationKnowledge",
        client: SharePointContentClient,
        stats: SyncStats,
        folder_id: Optional[str] = None,
        processed_items: set[str] | None = None,
    ):
        if processed_items is None:
            processed_items = set()

        if not drive_id:
            logger.warning(
                "Missing drive_id for SharePoint content fetch (integration_knowledge_id=%s)",
                integration_knowledge.id,
            )
            return

        if resource_type == "onedrive":
            if not folder_id:
                results = await client.get_drive_root_children(drive_id)
            else:
                results = await client.get_drive_folder_items(
                    drive_id=drive_id,
                    folder_id=folder_id,
                )
        else:
            if not site_id:
                logger.warning(
                    "Missing site_id for SharePoint folder fetch (drive_id=%s)",
                    drive_id,
                )
                return
            if not folder_id:
                results = await client.get_drive_root_children(drive_id)
            else:
                results = await client.get_folder_items(
                    site_id=site_id,
                    drive_id=drive_id,
                    folder_id=folder_id,
                )

        if not results:
            return

        await self._process_folder_results(
            site_id=site_id,
            drive_id=drive_id,
            resource_type=resource_type,
            client=client,
            results=results,
            integration_knowledge=integration_knowledge,
            processed_items=processed_items,
            stats=stats,
        )

    async def _process_folder_results(
        self,
        site_id: Optional[str],
        drive_id: str,
        resource_type: str,
        client: SharePointContentClient,
        results: list[SharePointItem],
        integration_knowledge: "IntegrationKnowledge",
        processed_items: set[str],
        stats: SyncStats,
    ) -> None:
        self._progress.add_total(self._file_count(results))
        await self._progress.set_phase("processing", stats)
        for item in results:
            item_id = item.get("id")

            if item_id in processed_items:
                continue

            if item_id:
                processed_items.add(item_id)

            item_type = self._get_item_type(item)
            await self._progress.update(
                stats, current=None if item_type == "folder" else item.get("name", "")
            )
            if item_type == "folder":
                stats["folders_processed"] += 1
                # Always recurse into folders to get their contents
                await self._fetch_and_process_content(
                    site_id=site_id,
                    drive_id=drive_id,
                    resource_type=resource_type,
                    client=client,
                    integration_knowledge=integration_knowledge,
                    folder_id=item_id,
                    processed_items=processed_items,
                    stats=stats,
                )
                continue

            await self._index.index_file(
                client=client,
                drive_id=drive_id,
                item=item,
                integration_knowledge=integration_knowledge,
                stats=stats,
            )

    async def token_refresh_callback(self, token_id: UUID) -> dict[str, str]:
        token = await self.oauth_token_service.refresh_and_update_token(
            token_id=token_id
        )
        return {
            "access_token": token.access_token,
            "refresh_token": token.refresh_token,
        }

    @staticmethod
    def _file_count(items: list[SharePointItem]) -> int:
        return sum(1 for item in items if not item.get("folder"))

    def _get_item_type(self, item: SharePointItem) -> str:
        if item.get("folder"):
            return "folder"

        return file_extension_to_type(item.get("name", ""))
