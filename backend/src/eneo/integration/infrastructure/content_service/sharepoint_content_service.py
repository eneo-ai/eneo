import asyncio
import hashlib
import unicodedata
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional, cast
from urllib.parse import unquote
from uuid import UUID

import sqlalchemy as sa

from eneo.database.tables.info_blob_chunk_table import InfoBlobChunks
from eneo.embedding_models.infrastructure.datastore import Datastore
from eneo.info_blobs.info_blob import InfoBlobAdd, InfoBlobUpdate
from eneo.integration.domain.entities.oauth_token import OauthToken
from eneo.integration.domain.entities.sync_log import SyncLog
from eneo.integration.domain.entities.tenant_sharepoint_app import (
    TenantSharePointApp,
)
from eneo.integration.infrastructure.clients.sharepoint_content_client import (
    DeltaTokenExpiredException,
    SharePointContentClient,
)
from eneo.integration.infrastructure.content_service.parsing import (
    extract_text_from_canvas_layout,
    has_graph_facet,
    require_text,
    safe_int,
    sanitize_text_for_db,
    unsupported_file_reason,
)
from eneo.integration.infrastructure.content_service.types import (
    SharePointItem,
    SharePointTokenProtocol,
    SyncMetadata,
    SyncStats,
)
from eneo.integration.infrastructure.content_service.utils import (
    file_extension_to_type,
    is_unextractable_content,
)
from eneo.integration.infrastructure.office_change_key_service import (
    OfficeChangeKeyService,
)
from eneo.main.logging import get_logger

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
    from eneo.integration.domain.repositories.user_integration_repo import (
        UserIntegrationRepository,
    )
    from eneo.integration.infrastructure.auth_service.service_account_auth_service import (
        ServiceAccountAuthService,
    )
    from eneo.integration.infrastructure.auth_service.tenant_app_auth_service import (
        TenantAppAuthService,
    )
    from eneo.integration.infrastructure.oauth_token_service import (
        OauthTokenService,
    )
    from eneo.jobs.job_service import JobService
    from eneo.users.user import UserInDB


logger = get_logger(__name__)

# Full-sync reconciliation safety guard: cap deletions at the LARGER of a fraction
# of the indexed set and a small absolute floor. The floor only lets a tiny KB churn
# fully; it is kept low so the fraction guard engages for medium KBs too (with the
# old floor of 50 the fraction was inert below 100 blobs). A diff above the cap almost
# always means a stale/incomplete enumeration, so we skip rather than mass-delete.
_RECONCILE_MAX_DELETE_FRACTION = 0.5
_RECONCILE_MIN_DELETE_FLOOR = 10


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


def _summary_counts(stats: SyncStats) -> dict[str, int]:
    return {
        "files_processed": stats.get("files_processed", 0),
        "files_deleted": stats.get("files_deleted", 0),
        "pages_processed": stats.get("pages_processed", 0),
        "folders_processed": stats.get("folders_processed", 0),
        "skipped_items": stats.get("skipped_items", 0),
    }


def _sync_metadata(
    stats: SyncStats | None = None,
    *,
    trigger: str,
    recovery: str | None = None,
    changes_detected: int | None = None,
) -> SyncMetadata:
    metadata: SyncMetadata = {"trigger": trigger}

    if stats is not None:
        metadata["files_processed"] = stats.get("files_processed", 0)
        metadata["files_deleted"] = stats.get("files_deleted", 0)
        metadata["out_of_scope_deleted"] = stats.get("out_of_scope_deleted", 0)
        metadata["pages_processed"] = stats.get("pages_processed", 0)
        metadata["folders_processed"] = stats.get("folders_processed", 0)
        metadata["skipped_items"] = stats.get("skipped_items", 0)
        metadata["skipped_details"] = stats.get("skipped_details", [])
    if recovery:
        metadata["recovery"] = recovery
    if changes_detected is not None:
        metadata["changes_detected"] = changes_detected

    return metadata


class SharePointContentService:
    def __init__(
        self,
        job_service: "JobService",
        oauth_token_repo: "OauthTokenRepository",
        user_integration_repo: "UserIntegrationRepository",
        user: "UserInDB",
        datastore: "Datastore",
        info_blob_service: "InfoBlobService",
        integration_knowledge_repo: "IntegrationKnowledgeRepository",
        oauth_token_service: "OauthTokenService",
        session: "AsyncSession",
        tenant_sharepoint_app_repo: "TenantSharePointAppRepository",
        tenant_app_auth_service: "TenantAppAuthService",
        service_account_auth_service: "ServiceAccountAuthService | None" = None,
        sync_log_repo: "SyncLogRepository | None" = None,
        change_key_service: "OfficeChangeKeyService | None" = None,
    ) -> None:
        super().__init__()
        self.job_service = job_service
        self.oauth_token_repo = oauth_token_repo
        self.user_integration_repo = user_integration_repo
        self.user = user
        self.datastore = datastore
        self.info_blob_service = info_blob_service
        self.integration_knowledge_repo = integration_knowledge_repo
        self.oauth_token_service = oauth_token_service
        self.session = session
        self.tenant_sharepoint_app_repo = tenant_sharepoint_app_repo
        self.tenant_app_auth_service = tenant_app_auth_service
        self.service_account_auth_service = service_account_auth_service
        self.sync_log_repo = sync_log_repo
        self.change_key_service = change_key_service
        # Strong refs to in-flight post-commit ChangeKey flush tasks so the event
        # loop does not GC them before they run.
        self._pending_change_key_tasks: set["asyncio.Task[None]"] = set()

    async def _refresh_service_account_access_token(
        self, tenant_app: TenantSharePointApp
    ) -> str:
        """Refresh service account token and persist refresh-token rotation."""
        if not self.service_account_auth_service:
            raise ValueError("ServiceAccountAuthService not configured")

        token_data = await self.service_account_auth_service.refresh_access_token(
            tenant_app
        )
        access_token = token_data["access_token"]
        new_refresh_token = token_data.get("refresh_token")

        if (
            new_refresh_token
            and new_refresh_token != tenant_app.service_account_refresh_token
        ):
            tenant_app.update_refresh_token(new_refresh_token)
            await self.tenant_sharepoint_app_repo.update(tenant_app)
            logger.debug(
                "Persisted rotated service account refresh token for tenant_app %s",
                tenant_app.id,
            )

        return access_token

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
        sync_log = None
        started_at = datetime.now(timezone.utc)
        resolved_integration_knowledge_id: UUID | None = integration_knowledge_id

        try:
            if tenant_app_id:
                tenant_app = await self.tenant_sharepoint_app_repo.get_by_id(
                    app_id=tenant_app_id
                )
                if not tenant_app:
                    raise ValueError(f"Tenant app {tenant_app_id} not found")
                # Use service account or tenant app auth based on auth_method
                if tenant_app.is_service_account():
                    access_token = await self._refresh_service_account_access_token(
                        tenant_app
                    )
                    logger.info(
                        f"Using service account auth for tenant_app {tenant_app_id}"
                    )
                else:
                    access_token = await self.tenant_app_auth_service.get_access_token(
                        tenant_app
                    )
                    logger.info(f"Using tenant app auth for tenant_app {tenant_app_id}")
                token = SimpleSharePointToken(access_token=access_token)
                oauth_token_id = None
            elif token_id:
                token = await self.oauth_token_repo.one(id=token_id)
                oauth_token_id = token.id
            else:
                raise ValueError("Either token_id or tenant_app_id must be provided")

            stats = self._initialize_stats()

            integration_knowledge = await self.integration_knowledge_repo.one(
                id=integration_knowledge_id
            )
            resolved_integration_knowledge_id = integration_knowledge.id
            resolved_site_id = site_id or integration_knowledge.site_id
            resolved_drive_id = drive_id or integration_knowledge.drive_id
            if site_id and not getattr(integration_knowledge, "site_id", None):
                integration_knowledge.site_id = site_id

            if drive_id:
                integration_knowledge.drive_id = drive_id
            if resource_type:
                integration_knowledge.resource_type = resource_type

            if folder_id:
                integration_knowledge.folder_id = folder_id

            if folder_path:
                integration_knowledge.folder_path = folder_path

            await self.integration_knowledge_repo.update(obj=integration_knowledge)

            await self._pull_content(
                token=_require_sharepoint_token(token),
                oauth_token_id=oauth_token_id,
                integration_knowledge_id=resolved_integration_knowledge_id,
                site_id=resolved_site_id,
                drive_id=resolved_drive_id,
                resource_type=resource_type,
                stats=stats,
            )
            summary_stats = self._build_summary_stats(stats)

            integration_knowledge = await self.integration_knowledge_repo.one(
                id=resolved_integration_knowledge_id
            )

            files_processed = summary_stats.get("files_processed", 0)
            files_deleted = summary_stats.get("files_deleted", 0)

            integration_knowledge.last_sync_summary = _summary_counts(summary_stats)
            if files_processed > 0 or files_deleted > 0:
                integration_knowledge.last_synced_at = datetime.now(timezone.utc)

            if not integration_knowledge.delta_token:
                try:
                    base_url = _require_sharepoint_token(token).base_url
                    async with SharePointContentClient(
                        base_url=base_url,
                        api_token=token.access_token,
                        token_id=oauth_token_id,
                        token_refresh_callback=(
                            self.token_refresh_callback if oauth_token_id else None
                        ),
                    ) as content_client:
                        actual_drive_id = resolved_drive_id
                        if not actual_drive_id and resolved_site_id:
                            actual_drive_id = await content_client.get_default_drive_id(
                                resolved_site_id
                            )
                        if actual_drive_id:
                            delta_token = await content_client.initialize_delta_token(
                                actual_drive_id
                            )
                            if delta_token:
                                integration_knowledge.delta_token = delta_token
                                logger.info(
                                    f"Initialized delta token for integration knowledge {resolved_integration_knowledge_id}"
                                )
                except Exception as e:
                    logger.warning(
                        f"Failed to initialize delta token for integration knowledge {resolved_integration_knowledge_id}: {e}"
                    )

            await self.integration_knowledge_repo.update(obj=integration_knowledge)

            if self.sync_log_repo:
                files_processed = summary_stats.get("files_processed", 0)
                files_deleted = summary_stats.get("files_deleted", 0)
                skipped_items = summary_stats.get("skipped_items", 0)

                if files_processed > 0 or files_deleted > 0 or skipped_items > 0:
                    sync_log = SyncLog(
                        integration_knowledge_id=resolved_integration_knowledge_id,
                        sync_type="full",
                        status="success",
                        started_at=started_at,
                        completed_at=datetime.now(timezone.utc),
                        metadata=_sync_metadata(
                            summary_stats,
                            trigger=sync_trigger,
                            recovery=recovery,
                        ),
                    )
                    await self.sync_log_repo.add(sync_log)
                else:
                    logger.info(
                        f"Skipping sync log creation for integration knowledge {resolved_integration_knowledge_id}: "
                        "no files processed or deleted"
                    )

            return self._format_summary_for_job(summary_stats)

        except Exception as e:
            # Log failed sync
            if self.sync_log_repo and resolved_integration_knowledge_id is not None:
                sync_log = SyncLog(
                    integration_knowledge_id=resolved_integration_knowledge_id,
                    sync_type="full",
                    status="error",
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc),
                    error_message=str(e),
                    metadata=_sync_metadata(trigger=sync_trigger, recovery=recovery),
                )
                await self.sync_log_repo.add(sync_log)

            logger.error(f"Error in pull_content: {e}")
            raise

    async def process_delta_changes(
        self,
        token_id: Optional[UUID] = None,
        tenant_app_id: Optional[UUID] = None,
        integration_knowledge_id: UUID | None = None,
        site_id: Optional[str] = None,
        drive_id: Optional[str] = None,
        resource_type: str = "site",
        sync_trigger: str = "webhook",
    ) -> str:
        started_at = datetime.now(timezone.utc)
        resolved_integration_knowledge_id: UUID | None = integration_knowledge_id

        try:
            if tenant_app_id:
                tenant_app = await self.tenant_sharepoint_app_repo.get_by_id(
                    app_id=tenant_app_id
                )
                if not tenant_app:
                    raise ValueError(f"Tenant app {tenant_app_id} not found")
                # Use service account or tenant app auth based on auth_method
                if tenant_app.is_service_account():
                    access_token = await self._refresh_service_account_access_token(
                        tenant_app
                    )
                    logger.info(
                        f"Using service account auth for delta sync tenant_app {tenant_app_id}"
                    )
                else:
                    access_token = await self.tenant_app_auth_service.get_access_token(
                        tenant_app
                    )
                    logger.info(
                        f"Using tenant app auth for delta sync tenant_app {tenant_app_id}"
                    )
                token = SimpleSharePointToken(access_token=access_token)
                oauth_token_id = None
            elif token_id:
                token = await self.oauth_token_repo.one(id=token_id)
                oauth_token_id = token.id
            else:
                raise ValueError("Either token_id or tenant_app_id must be provided")

            integration_knowledge = await self.integration_knowledge_repo.one(
                id=integration_knowledge_id
            )
            resolved_integration_knowledge_id = integration_knowledge.id
            resolved_site_id = site_id or integration_knowledge.site_id
            resolved_drive_id = drive_id or integration_knowledge.drive_id
            if integration_knowledge.delta_token is None:
                site_id = resolved_site_id
                drive_id = resolved_drive_id

            if not integration_knowledge.delta_token:
                logger.warning(
                    f"No delta token found for integration knowledge {integration_knowledge_id}, "
                    "falling back to full sync"
                )
                return await self.pull_content(
                    token_id=token_id,
                    tenant_app_id=tenant_app_id,
                    integration_knowledge_id=resolved_integration_knowledge_id,
                    site_id=resolved_site_id,
                    drive_id=resolved_drive_id,
                    resource_type=resource_type
                    or integration_knowledge.resource_type
                    or "site",
                    sync_trigger=sync_trigger,
                    recovery="missing_delta_token",
                )

            stats = self._initialize_stats()

            base_url = _require_sharepoint_token(token).base_url
            async with SharePointContentClient(
                base_url=base_url,
                api_token=token.access_token,
                token_id=oauth_token_id,
                token_refresh_callback=(
                    self.token_refresh_callback if oauth_token_id else None
                ),
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
                    await self.integration_knowledge_repo.update(
                        obj=integration_knowledge
                    )
                    return await self.pull_content(
                        token_id=token_id,
                        tenant_app_id=tenant_app_id,
                        integration_knowledge_id=resolved_integration_knowledge_id,
                        site_id=resolved_site_id,
                        drive_id=resolved_drive_id,
                        resource_type=resource_type
                        or integration_knowledge.resource_type
                        or "site",
                        sync_trigger=sync_trigger,
                        recovery="delta_token_expired",
                    )
                logger.info(
                    f"Delta query returned {len(changes)} items. New token: {new_delta_token[:20] if new_delta_token else 'None'}..."
                )

                scope_folder_path = integration_knowledge.folder_path
                known_subfolder_ids: set[str] = set()
                folder_scope_path_unresolved = False
                if (
                    integration_knowledge.selected_item_type == "folder"
                    and integration_knowledge.folder_id
                    and not scope_folder_path
                ):
                    # Legacy integrations may miss folder_path. Resolve it once so
                    # nested delta changes in subfolders stay in scope.
                    try:
                        folder_metadata = await content_client.get_file_metadata(
                            drive_id=actual_drive_id,
                            item_id=integration_knowledge.folder_id,
                        )
                        resolved_folder_path = self._folder_path_from_item(
                            cast(SharePointItem, folder_metadata)
                        )

                        if resolved_folder_path:
                            scope_folder_path = resolved_folder_path
                            integration_knowledge.folder_path = resolved_folder_path
                            await self.integration_knowledge_repo.update(
                                obj=integration_knowledge
                            )
                        else:
                            logger.warning(
                                "Could not derive folder_path for delta scope "
                                "(integration_knowledge=%s, folder_id=%s)",
                                resolved_integration_knowledge_id,
                                integration_knowledge.folder_id,
                            )
                            folder_scope_path_unresolved = True
                    except Exception as exc:
                        logger.warning(
                            "Could not resolve folder_path for delta scope (integration_knowledge=%s, folder_id=%s): %s",
                            resolved_integration_knowledge_id,
                            integration_knowledge.folder_id,
                            exc,
                        )
                        folder_scope_path_unresolved = True

                if len(changes) == 0:
                    logger.info(
                        f"Delta query returned 0 changes for integration knowledge {integration_knowledge_id}. "
                        "No updates needed - SharePoint is in sync with database."
                    )

                    if new_delta_token:
                        integration_knowledge.delta_token = new_delta_token

                    summary_stats: SyncStats = {
                        "files_processed": 0,
                        "files_deleted": 0,
                        "out_of_scope_deleted": 0,
                        "pages_processed": 0,
                        "folders_processed": 0,
                        "skipped_items": 0,
                        "skipped_details": [],
                    }

                    integration_knowledge.last_sync_summary = _summary_counts(
                        summary_stats
                    )
                    await self.integration_knowledge_repo.update(
                        obj=integration_knowledge
                    )

                    logger.info("Delta sync completed: no changes detected")
                    return self._format_summary_for_job(summary_stats)

                logger.info(f"Processing {len(changes)} changed items from delta query")
                # Accumulate processed (item_id, change_key) pairs and write them to
                # the Redis ChangeKey cache only after the DB transaction commits.
                # See _schedule_post_commit_change_keys for why.
                pending_change_keys: list[tuple[UUID, str, str]] = []
                for item in changes:
                    item_name = item.get("name", "")
                    item_id = item.get("id")
                    is_deleted = has_graph_facet(item, "deleted")
                    is_folder = has_graph_facet(item, "folder")
                    change_key = item.get("cTag")

                    logger.debug(
                        f"  - Item: {item_name} (deleted={is_deleted}, folder={is_folder}, changeKey={change_key})"
                    )

                    if not item_id:
                        stats["skipped_items"] += 1
                        stats["skipped_details"].append(
                            {
                                "file": item_name or "unknown",
                                "reason": "Missing item id",
                            }
                        )
                        continue

                    # Skip scope check for deleted items — they may lack
                    # parentReference data.  The DB delete queries already
                    # filter by integration_knowledge_id so they are safe.
                    if not is_deleted and not self._is_item_in_folder_scope(
                        item,
                        integration_knowledge.folder_id,
                        scope_folder_path=scope_folder_path,
                        known_subfolder_ids=known_subfolder_ids,
                        selected_item_type=integration_knowledge.selected_item_type,
                    ):
                        if (
                            folder_scope_path_unresolved
                            and integration_knowledge.selected_item_type == "folder"
                            and integration_knowledge.folder_id
                            and not scope_folder_path
                        ):
                            logger.warning(
                                "Skipping destructive out-of-scope cleanup for %s "
                                "(item_id=%s) because folder_path could not be resolved "
                                "for integration_knowledge %s",
                                item_name,
                                item_id,
                                resolved_integration_knowledge_id,
                            )
                            stats["skipped_items"] += 1
                            stats["skipped_details"].append(
                                {
                                    "file": item_name or item_id,
                                    "reason": "Folder scope path unavailable",
                                }
                            )
                            continue

                        logger.debug(
                            f"  - Skipping item {item_name}: not in folder scope"
                        )
                        await self._delete_local_sharepoint_item(
                            item_id=item_id,
                            item_name=item_name,
                            integration_knowledge=integration_knowledge,
                            integration_knowledge_id=resolved_integration_knowledge_id,
                            stats=stats,
                            reason="out-of-scope",
                        )
                        # A folder that left scope still exists in SharePoint, but Graph
                        # does not re-emit its (unchanged) children — deleting only the
                        # folder id would orphan every descendant blob. Enumerate the
                        # folder's current descendants and remove them too.
                        if is_folder:
                            await self._delete_out_of_scope_folder_subtree(
                                content_client=content_client,
                                resource_type=integration_knowledge.resource_type
                                or "site",
                                site_id=resolved_site_id,
                                drive_id=actual_drive_id,
                                folder_id=item_id,
                                folder_name=item_name,
                                integration_knowledge=integration_knowledge,
                                integration_knowledge_id=resolved_integration_knowledge_id,
                                stats=stats,
                            )
                        continue

                    if (
                        is_folder
                        and item_id
                        and integration_knowledge.selected_item_type == "folder"
                    ):
                        known_subfolder_ids.add(item_id)
                        if item_id == integration_knowledge.folder_id:
                            updated_folder_path = self._folder_path_from_item(item)
                            if updated_folder_path:
                                scope_folder_path = updated_folder_path
                                integration_knowledge.folder_path = updated_folder_path

                    if is_deleted:
                        # Delete the corresponding info_blob if it exists
                        await self._delete_local_sharepoint_item(
                            item_id=item_id,
                            item_name=item_name,
                            integration_knowledge=integration_knowledge,
                            integration_knowledge_id=resolved_integration_knowledge_id,
                            stats=stats,
                            reason="removed",
                        )
                        continue

                    if is_folder:
                        stats["folders_processed"] += 1
                        continue

                    should_process = True
                    if self.change_key_service and item_id and change_key:
                        should_process = await self.change_key_service.should_process(
                            integration_knowledge_id=resolved_integration_knowledge_id,
                            item_id=item_id,
                            change_key=change_key,
                        )

                    if not should_process:
                        logger.info(
                            f"Skipping item {item_name} (ID: {item_id}): ChangeKey already processed (duplicate)"
                        )
                        stats["skipped_items"] += 1
                        stats["skipped_details"].append(
                            {"file": item_name, "reason": "Already synced (no changes)"}
                        )
                        continue

                    unsupported_reason = unsupported_file_reason(item_name)
                    if unsupported_reason:
                        stats["skipped_items"] += 1
                        stats["skipped_details"].append(
                            {"file": item_name, "reason": unsupported_reason}
                        )
                        continue

                    web_url = item.get("webUrl", "")

                    try:
                        content, _ = await content_client.get_file_content_by_id(
                            drive_id=actual_drive_id,
                            item_id=item_id,
                        )

                        if content and not is_unextractable_content(content):
                            await self._process_info_blob(
                                title=item_name,
                                text=content,
                                url=web_url,
                                integration_knowledge=integration_knowledge,
                                sharepoint_item_id=item_id,
                            )
                            stats["files_processed"] += 1

                            # Defer the ChangeKey cache write until after commit so a
                            # rolled-back sync re-processes the item instead of skipping it.
                            if self.change_key_service and item_id and change_key:
                                pending_change_keys.append(
                                    (
                                        resolved_integration_knowledge_id,
                                        item_id,
                                        change_key,
                                    )
                                )
                        else:
                            await self._delete_local_blob_for_unextractable_item(
                                item_id=item_id,
                                item_name=item_name,
                                integration_knowledge=integration_knowledge,
                                integration_knowledge_id=resolved_integration_knowledge_id,
                                stats=stats,
                            )

                    except ValueError as e:
                        if "exceeds max download size" in str(e):
                            reason = "File too large (exceeds 50 MB limit)"
                        else:
                            reason = f"Error: {e}"
                        logger.error(f"Error processing changed file {item_name}: {e}")
                        stats["skipped_items"] += 1
                        stats["skipped_details"].append(
                            {"file": item_name, "reason": reason}
                        )
                    except Exception as e:
                        logger.error(f"Error processing changed file {item_name}: {e}")
                        stats["skipped_items"] += 1
                        stats["skipped_details"].append(
                            {"file": item_name, "reason": f"Error: {e}"}
                        )

                integration_knowledge.delta_token = new_delta_token

                summary_stats = self._build_summary_stats(stats)
                integration_knowledge.last_sync_summary = _summary_counts(summary_stats)

                files_processed = summary_stats.get("files_processed", 0)
                files_deleted = summary_stats.get("files_deleted", 0)
                if files_processed > 0 or files_deleted > 0:
                    integration_knowledge.last_synced_at = datetime.now(timezone.utc)

                logger.info(f"Delta sync completed: {summary_stats}")

                await self.integration_knowledge_repo.update(obj=integration_knowledge)

                self._schedule_post_commit_change_keys(pending_change_keys)

                logger.info(
                    f"Processed {len(changes)} delta changes for integration knowledge {resolved_integration_knowledge_id}"
                )

                if self.sync_log_repo:
                    files_processed = summary_stats.get("files_processed", 0)
                    files_deleted = summary_stats.get("files_deleted", 0)
                    skipped_items = summary_stats.get("skipped_items", 0)

                    if files_processed > 0 or files_deleted > 0 or skipped_items > 0:
                        sync_log = SyncLog(
                            integration_knowledge_id=resolved_integration_knowledge_id,
                            sync_type="delta",
                            status="success",
                            started_at=started_at,
                            completed_at=datetime.now(timezone.utc),
                            metadata=_sync_metadata(
                                summary_stats,
                                trigger=sync_trigger,
                                changes_detected=len(changes),
                            ),
                        )
                        await self.sync_log_repo.add(sync_log)
                    else:
                        logger.info(
                            f"Skipping sync log creation for integration knowledge {integration_knowledge_id}: "
                            "no files processed or deleted"
                        )

                return self._format_summary_for_job(summary_stats)

        except Exception as e:
            # Log failed delta sync
            if self.sync_log_repo and resolved_integration_knowledge_id is not None:
                sync_log = SyncLog(
                    integration_knowledge_id=resolved_integration_knowledge_id,
                    sync_type="delta",
                    status="error",
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc),
                    error_message=str(e),
                    metadata=_sync_metadata(trigger=sync_trigger),
                )
                await self.sync_log_repo.add(sync_log)

            logger.error(f"Error processing delta changes: {e}")
            raise

    async def _pull_content(
        self,
        token: SharePointTokenProtocol,
        oauth_token_id: Optional[UUID],
        integration_knowledge_id: UUID,
        site_id: Optional[str],
        drive_id: Optional[str],
        resource_type: str,
        stats: SyncStats,
    ) -> SyncStats:
        """
        Process content from SharePoint site or OneDrive.

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

        try:
            site_id_value = site_id
            if resource_type != "onedrive":
                site_id_value = require_text(site_id_value, "site_id")

            base_url = token.base_url
            async with SharePointContentClient(
                base_url=base_url,
                api_token=token.access_token,
                token_id=oauth_token_id,
                token_refresh_callback=(
                    self.token_refresh_callback if oauth_token_id else None
                ),
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

                if integration_knowledge.folder_id:
                    folder_id_value = require_text(
                        integration_knowledge.folder_id, "folder_id"
                    )
                    item_info = await content_client.get_file_metadata(
                        drive_id=actual_drive_id,
                        item_id=folder_id_value,
                    )

                    is_folder = item_info.get("folder") is not None
                    item_name = item_info.get("name", "")

                    if is_folder:
                        logger.info(
                            f"Processing folder '{item_name}' (ID: {folder_id_value}) "
                            f"for integration knowledge {integration_knowledge_id}"
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
                        refreshed_folder_path = self._folder_path_from_item(
                            cast(SharePointItem, item_info)
                        )
                        if (
                            refreshed_folder_path
                            and refreshed_folder_path
                            != integration_knowledge.folder_path
                        ):
                            integration_knowledge.folder_path = refreshed_folder_path
                            await self.integration_knowledge_repo.update(
                                obj=integration_knowledge
                            )
                        processed_items: set[str] = set()
                        await self._fetch_and_process_content(
                            site_id=site_id_value,
                            drive_id=actual_drive_id,
                            resource_type=resource_type,
                            client=content_client,
                            token=token,
                            integration_knowledge_id=integration_knowledge_id,
                            folder_id=folder_id_value,
                            processed_items=processed_items,
                            stats=stats,
                            is_root_call=True,
                        )
                        await self._reconcile_indexed_blobs(
                            client=content_client,
                            integration_knowledge=integration_knowledge,
                            resource_type=resource_type,
                            site_id=site_id_value,
                            drive_id=actual_drive_id,
                            folder_id=folder_id_value,
                            stats=stats,
                        )
                        return stats
                    else:
                        logger.info(
                            f"Processing single file '{item_name}' (ID: {folder_id_value}) "
                            f"for integration knowledge {integration_knowledge_id}"
                        )
                        integration_knowledge.selected_item_type = "file"

                        unsupported_reason = unsupported_file_reason(item_name)
                        if unsupported_reason:
                            stats["skipped_items"] += 1
                            stats["skipped_details"].append(
                                {"file": item_name, "reason": unsupported_reason}
                            )
                            return stats

                        try:
                            content, _ = await content_client.get_file_content_by_id(
                                drive_id=actual_drive_id,
                                item_id=folder_id_value,
                            )
                        except Exception as e:
                            logger.error(
                                f"Error getting file content for {item_name}: {e}"
                            )
                            stats["skipped_items"] += 1
                            stats["skipped_details"].append(
                                {"file": item_name, "reason": f"Error: {e}"}
                            )
                            return stats

                        if content and not is_unextractable_content(content):
                            await self._process_info_blob(
                                title=item_name,
                                text=content,
                                url=item_info.get("webUrl", ""),
                                integration_knowledge=integration_knowledge,
                                sharepoint_item_id=integration_knowledge.folder_id,
                            )
                            stats["files_processed"] += 1
                        else:
                            await self._delete_local_blob_for_unextractable_item(
                                item_id=folder_id_value,
                                item_name=item_name,
                                integration_knowledge=integration_knowledge,
                                integration_knowledge_id=integration_knowledge_id,
                                stats=stats,
                            )

                        return stats
                else:
                    integration_knowledge.selected_item_type = "site_root"

                    if resource_type == "onedrive":
                        data = await content_client.get_drive_root_children(
                            actual_drive_id
                        )
                    else:
                        data = await content_client.get_documents_in_drive(
                            site_id=require_text(site_id_value, "site_id")
                        )

                    if data:
                        await self._process_documents(
                            documents=data,
                            client=content_client,
                            integration_knowledge=integration_knowledge,
                            token=token,
                            resource_type=resource_type,
                            stats=stats,
                        )

                    if resource_type != "onedrive" and site_id_value:
                        pages = await content_client.get_site_pages(
                            site_id=require_text(site_id_value, "site_id")
                        )
                        if data := pages.get("value", []):
                            await self._process_pages(
                                pages=data,
                                client=content_client,
                                integration_knowledge=integration_knowledge,
                                stats=stats,
                            )

                    await self._reconcile_indexed_blobs(
                        client=content_client,
                        integration_knowledge=integration_knowledge,
                        resource_type=resource_type,
                        site_id=site_id_value,
                        drive_id=actual_drive_id,
                        folder_id=None,
                        stats=stats,
                    )

        except Exception as e:
            logger.error(f"Error processing document {site_id}: {e}")
            raise

        return stats

    async def _process_documents(
        self,
        documents: list[SharePointItem],
        client: SharePointContentClient,
        integration_knowledge: "IntegrationKnowledge",
        token: SharePointTokenProtocol,
        resource_type: str,
        stats: SyncStats,
    ):
        for document in documents:
            drive_id = document.get("parentReference", {}).get("driveId")
            site_id = document.get("parentReference", {}).get("siteId")
            item_id = document.get("id")
            if document.get("folder", {}):
                if not drive_id or not item_id:
                    continue
                stats["folders_processed"] += 1
                # Recursively process all items in the folder
                processed_items: set[str] = set()
                await self._fetch_and_process_content(
                    site_id=site_id,
                    drive_id=drive_id,
                    resource_type=resource_type,
                    client=client,
                    token=token,
                    integration_knowledge_id=integration_knowledge.id,
                    folder_id=item_id,
                    processed_items=processed_items,
                    stats=stats,
                    is_root_call=False,
                )
            else:
                # file
                if not drive_id or not item_id:
                    continue
                doc_name = document.get("name", "")
                unsupported_reason = unsupported_file_reason(doc_name)
                if unsupported_reason:
                    stats["skipped_items"] += 1
                    stats["skipped_details"].append(
                        {"file": doc_name, "reason": unsupported_reason}
                    )
                    continue
                try:
                    content, _ = await client.get_file_content_by_id(
                        drive_id=drive_id, item_id=item_id
                    )
                except Exception as e:
                    logger.error(f"Error getting file content for {doc_name}: {e}")
                    stats["skipped_items"] += 1
                    stats["skipped_details"].append(
                        {"file": doc_name, "reason": f"Error: {e}"}
                    )
                    continue

                if content and not is_unextractable_content(content):
                    await self._process_info_blob(
                        title=doc_name,
                        text=content,
                        url=document.get("webUrl", ""),
                        integration_knowledge=integration_knowledge,
                        sharepoint_item_id=item_id,
                    )
                    stats["files_processed"] += 1
                else:
                    await self._delete_local_blob_for_unextractable_item(
                        item_id=item_id,
                        item_name=doc_name,
                        integration_knowledge=integration_knowledge,
                        integration_knowledge_id=integration_knowledge.id,
                        stats=stats,
                    )

    async def _process_pages(
        self,
        pages: list[SharePointItem],
        client: SharePointContentClient,
        integration_knowledge: "IntegrationKnowledge",
        stats: SyncStats,
    ):
        for page in pages:
            site_id = page.get("parentReference", {}).get("siteId")
            page_id = page.get("id")
            if not site_id or not page_id:
                continue
            content = await client.get_page_content(site_id=site_id, page_id=page_id)
            if content:
                page_text = extract_text_from_canvas_layout(content)
                if not page_text:
                    page_text = content.get("description", "")
                await self._process_info_blob(
                    title=content.get("title", ""),
                    text=page_text,
                    url=content.get("webUrl", ""),
                    integration_knowledge=integration_knowledge,
                    sharepoint_item_id=page.get("id"),
                )
                stats["pages_processed"] += 1
            else:
                page_name = (
                    page.get("name", "")
                    or page.get("title", "")
                    or f"Page {page.get('id', 'unknown')}"
                )
                stats["skipped_items"] += 1
                stats["skipped_details"].append(
                    {"file": page_name, "reason": "Empty or unreadable content"}
                )

    async def _process_info_blob(
        self,
        title: str,
        text: str,
        url: str,
        integration_knowledge: "IntegrationKnowledge",
        sharepoint_item_id: Optional[str] = None,
    ) -> None:
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

        sanitized_text = sanitize_text_for_db(text)
        content_hash = hashlib.sha256(sanitized_text.encode("utf-8")).digest()

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
            if existing_blob.title != title or existing_blob.url != url:
                await self.info_blob_service.repo.update(
                    InfoBlobUpdate(
                        id=existing_blob.id,
                        user_id=self.user.id,
                        title=title,
                        url=url,
                    )
                )
            logger.debug(
                "Skipping re-embed for unchanged SharePoint content: %s (item_id=%s)",
                title,
                sharepoint_item_id,
            )
            return

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
            content_hash=None,
        )

        if sharepoint_item_id:
            info_blob = await self.info_blob_service.upsert_info_blob_by_sharepoint_item_and_integration(
                info_blob_add
            )
        else:
            info_blob = (
                await self.info_blob_service.upsert_info_blob_by_title_and_integration(
                    info_blob_add
                )
            )

        try:
            await self.info_blob_service.repo.session.execute(
                sa.delete(InfoBlobChunks).where(
                    InfoBlobChunks.info_blob_id == info_blob.id
                )
            )
            logger.debug(f"Cleared old chunks for {title}")
        except Exception as e:
            logger.warning(f"Could not delete old chunks for {title}: {e}")

        try:
            await self.datastore.add(
                info_blob=info_blob,
                embedding_model=integration_knowledge.embedding_model,
            )
        except Exception as e:
            logger.debug(f"Could not add embedding for {title}: {e}")
        else:
            await self.info_blob_service.repo.update_content_hash(
                info_blob_id=info_blob.id,
                content_hash=content_hash,
            )

        current_size = safe_int(getattr(integration_knowledge, "size", 0))
        new_blob_size = safe_int(getattr(info_blob, "size", 0))
        size_delta = new_blob_size - previous_blob_size
        if size_delta:
            integration_knowledge.size = max(0, current_size + size_delta)
            await self.integration_knowledge_repo.update(obj=integration_knowledge)

    async def _delete_local_sharepoint_item(
        self,
        *,
        item_id: str,
        item_name: str,
        integration_knowledge: "IntegrationKnowledge",
        integration_knowledge_id: UUID,
        stats: SyncStats,
        reason: str,
    ) -> int:
        """Remove a locally indexed SharePoint item from one integration knowledge."""
        try:
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
                current_size = safe_int(getattr(integration_knowledge, "size", 0))
                deleted_size = sum(
                    safe_int(getattr(blob, "size", 0)) for blob in valid_deleted_blobs
                )
                integration_knowledge.size = max(0, current_size - deleted_size)

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
            stats["skipped_items"] += 1
            stats["skipped_details"].append(
                {"file": item_name, "reason": f"Could not remove {reason}: {e}"}
            )
            return 0

    async def _delete_local_blob_for_unextractable_item(
        self,
        *,
        item_id: str,
        item_name: str,
        integration_knowledge: "IntegrationKnowledge",
        integration_knowledge_id: UUID,
        stats: SyncStats,
    ) -> None:
        reason = "Empty or unreadable content"
        stats["skipped_items"] += 1
        stats["skipped_details"].append({"file": item_name, "reason": reason})
        await self._delete_local_sharepoint_item(
            item_id=item_id,
            item_name=item_name,
            integration_knowledge=integration_knowledge,
            integration_knowledge_id=integration_knowledge_id,
            stats=stats,
            reason="unextractable",
        )

    @staticmethod
    def _is_positive_unextractable_result(
        content: Optional[str], skip_reason: Optional[str]
    ) -> bool:
        if content is not None:
            return is_unextractable_content(content)
        return skip_reason == "Empty or unreadable content"

    async def _delete_out_of_scope_folder_subtree(
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
    ) -> None:
        """Remove indexed blobs for every descendant of a folder that left scope.

        SharePoint/OneDrive delta only re-emits the moved folder, not its
        unchanged children, so deleting just the folder id would orphan the whole
        subtree (stale RAG hits). The folder still exists at its new location, so
        enumerate its current descendants via Graph and delete their blobs. Uses the
        same strict enumeration as reconciliation, which handles both SharePoint
        (needs site_id) and OneDrive (drive-only), so OneDrive subtrees are cleaned
        inline rather than waiting for a full sync that may never come.
        """
        if not drive_id:
            return

        try:
            descendant_ids = await self._enumerate_authoritative_item_ids(
                client=content_client,
                resource_type=resource_type,
                site_id=site_id,
                drive_id=drive_id,
                folder_id=folder_id,
            )
        except Exception as exc:
            logger.warning(
                "Failed to enumerate out-of-scope subtree for folder %s (%s): %s; "
                "descendants will be reconciled on the next full sync",
                folder_name,
                folder_id,
                exc,
            )
            return

        for descendant_id in descendant_ids:
            await self._delete_local_sharepoint_item(
                item_id=descendant_id,
                item_name=descendant_id,
                integration_knowledge=integration_knowledge,
                integration_knowledge_id=integration_knowledge_id,
                stats=stats,
                reason="out-of-scope-subtree",
            )

    def _schedule_post_commit_change_keys(
        self, pending: list[tuple[UUID, str, str]]
    ) -> None:
        """Write the Redis ChangeKey cache only after the DB transaction commits.

        Writing inline would let Redis claim an item is processed while its
        info_blob write is still uncommitted; a rollback (e.g. a lease-loss
        ``CancelledError`` that bypasses the per-item ``except``) would then skip
        the item until the 7-day TTL or a 410 resync. Deferring to ``after_commit``
        means a failed/rolled-back sync simply re-processes the item next time —
        the safe direction.

        The flush is a deliberate fire-and-forget task (a sync ``after_commit`` event
        cannot await). If the worker is killed in the tiny window between commit and
        flush the ChangeKey is lost, but that fails in the same safe direction: the
        next sync re-downloads the item and the content_hash check skips the (costly)
        re-embed, so the only cost is a redundant download. Not worth blocking the
        event loop with a synchronous Redis write to close it.
        """
        if not pending or not self.change_key_service:
            return

        sync_session = getattr(self.session, "sync_session", None)
        if sync_session is None:
            return

        def _on_after_commit(_sync_session: object) -> None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
            task = loop.create_task(self._flush_change_keys(pending))
            self._pending_change_key_tasks.add(task)
            task.add_done_callback(self._pending_change_key_tasks.discard)

        try:
            sa.event.listen(sync_session, "after_commit", _on_after_commit, once=True)
        except Exception as exc:
            # Defensive: a non-ORM session (e.g. in unit tests) cannot register
            # events. Skipping is the safe direction — the item re-processes next sync.
            logger.warning("Could not register post-commit ChangeKey flush: %s", exc)

    async def _flush_change_keys(self, pending: list[tuple[UUID, str, str]]) -> None:
        if not self.change_key_service:
            return
        for integration_knowledge_id, item_id, change_key in pending:
            try:
                await self.change_key_service.update_change_key(
                    integration_knowledge_id=integration_knowledge_id,
                    item_id=item_id,
                    change_key=change_key,
                )
            except Exception as exc:
                logger.warning(
                    "Deferred ChangeKey write failed for item %s: %s", item_id, exc
                )

    async def _enumerate_authoritative_item_ids(
        self,
        *,
        client: SharePointContentClient,
        resource_type: str,
        site_id: Optional[str],
        drive_id: str,
        folder_id: Optional[str],
    ) -> set[str]:
        """Strictly enumerate every in-scope file (and page) item id.

        Unlike _collect_files_recursive, this propagates listing errors instead of
        swallowing them: an incomplete enumeration must NOT be treated as the
        authoritative set during reconciliation, or it would delete valid blobs.
        """
        item_ids: set[str] = set()

        async def _walk(current_folder_id: Optional[str]) -> None:
            if resource_type == "onedrive":
                results = (
                    await client.get_drive_root_children(drive_id)
                    if not current_folder_id
                    else await client.get_drive_folder_items(
                        drive_id=drive_id, folder_id=current_folder_id
                    )
                )
            elif not site_id:
                raise ValueError("site_id required to enumerate SharePoint drive items")
            elif not current_folder_id:
                results = await client.get_documents_in_drive(site_id=site_id)
            else:
                results = await client.get_folder_items(
                    site_id=site_id, drive_id=drive_id, folder_id=current_folder_id
                )

            for item in results or []:
                item_id = item.get("id")
                if has_graph_facet(item, "folder"):
                    if item_id:
                        await _walk(item_id)
                elif item_id:
                    item_ids.add(item_id)

        await _walk(folder_id)

        # Site pages live alongside drive documents for site-root SharePoint scopes.
        if resource_type != "onedrive" and site_id and folder_id is None:
            pages = await client.get_site_pages(site_id=site_id)
            for page in pages.get("value", []):
                page_id = page.get("id")
                if page_id:
                    item_ids.add(page_id)

        return item_ids

    async def _reconcile_indexed_blobs(
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
            authoritative_ids = await self._enumerate_authoritative_item_ids(
                client=client,
                resource_type=resource_type,
                site_id=site_id,
                drive_id=drive_id,
                folder_id=folder_id,
            )
            indexed = await self.info_blob_service.repo.get_sharepoint_item_ids_for_integration_knowledge(
                integration_knowledge_id=integration_knowledge.id
            )
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
            )
            return

        if not orphans:
            return

        cap = max(
            _RECONCILE_MIN_DELETE_FLOOR,
            int(len(indexed) * _RECONCILE_MAX_DELETE_FRACTION),
        )
        if len(orphans) > cap:
            logger.error(
                "Skipping reconciliation for integration_knowledge %s: would delete "
                "%d of %d blobs (> safety cap %d) — likely an incomplete enumeration.",
                integration_knowledge.id,
                len(orphans),
                len(indexed),
                cap,
            )
            return

        logger.info(
            "Reconciliation removing %d orphaned blob(s) for integration_knowledge %s",
            len(orphans),
            integration_knowledge.id,
        )
        deleted_count = 0
        for _blob_id, item_id in orphans:
            deleted_count += await self._delete_local_sharepoint_item(
                item_id=item_id,
                item_name=item_id,
                integration_knowledge=integration_knowledge,
                integration_knowledge_id=integration_knowledge.id,
                stats=stats,
                reason="reconcile-orphan",
            )
        if deleted_count:
            await self.integration_knowledge_repo.update(obj=integration_knowledge)

    async def _fetch_and_process_content(
        self,
        site_id: Optional[str],
        drive_id: Optional[str],
        resource_type: str,
        token: SharePointTokenProtocol,
        integration_knowledge_id: UUID,
        client: SharePointContentClient,
        stats: SyncStats,
        folder_id: Optional[str] = None,
        processed_items: set[str] | None = None,
        is_root_call: bool = True,
    ):
        if processed_items is None:
            processed_items = set()

        if not drive_id:
            logger.warning(
                "Missing drive_id for SharePoint content fetch (integration_knowledge_id=%s)",
                integration_knowledge_id,
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
                results = await client.get_documents_in_drive(site_id=site_id)
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
            integration_knowledge_id=integration_knowledge_id,
            token=token,
            processed_items=processed_items,
            stats=stats,
            is_root_call=is_root_call,
        )

    async def _process_folder_results(
        self,
        site_id: Optional[str],
        drive_id: str,
        resource_type: str,
        client: SharePointContentClient,
        results: list[SharePointItem],
        integration_knowledge_id: UUID,
        token: SharePointTokenProtocol,
        processed_items: set[str],
        stats: SyncStats,
        is_root_call: bool = True,
    ) -> None:
        integration_knowledge = await self.integration_knowledge_repo.one(
            id=integration_knowledge_id
        )

        for item in results:
            item_id = item.get("id")

            if item_id in processed_items:
                continue

            if item_id:
                processed_items.add(item_id)

            item_name = item.get("name", "")
            item_type = self._get_item_type(item)
            web_url = item.get("webUrl", "")

            if item_type == "folder":
                stats["folders_processed"] += 1
                # Always recurse into folders to get their contents
                await self._fetch_and_process_content(
                    site_id=site_id,
                    drive_id=drive_id,
                    resource_type=resource_type,
                    client=client,
                    token=token,
                    integration_knowledge_id=integration_knowledge_id,
                    folder_id=item_id,
                    processed_items=processed_items,
                    stats=stats,
                    is_root_call=False,
                )
                continue

            content, skip_reason = await self._get_file_content(client, item)

            if content and not is_unextractable_content(content):
                await self._process_info_blob(
                    title=item_name,
                    text=content,
                    url=web_url,
                    integration_knowledge=integration_knowledge,
                    sharepoint_item_id=item_id,
                )
                stats["files_processed"] += 1
            elif item_id and self._is_positive_unextractable_result(
                content, skip_reason
            ):
                await self._delete_local_blob_for_unextractable_item(
                    item_id=item_id,
                    item_name=item_name,
                    integration_knowledge=integration_knowledge,
                    integration_knowledge_id=integration_knowledge_id,
                    stats=stats,
                )
            else:
                stats["skipped_items"] += 1
                if skip_reason:
                    stats["skipped_details"].append(
                        {"file": item_name, "reason": skip_reason}
                    )

    def _initialize_stats(self) -> SyncStats:
        return {
            "files_processed": 0,
            "files_deleted": 0,
            "out_of_scope_deleted": 0,
            "folders_processed": 0,
            "pages_processed": 0,
            "skipped_items": 0,
            "skipped_details": [],
        }

    def _build_summary_stats(self, stats: SyncStats) -> SyncStats:
        summary: SyncStats = {
            "files_processed": stats.get("files_processed", 0),
            "files_deleted": stats.get("files_deleted", 0),
            "out_of_scope_deleted": stats.get("out_of_scope_deleted", 0),
            "pages_processed": stats.get("pages_processed", 0),
            "folders_processed": stats.get("folders_processed", 0),
            "skipped_items": stats.get("skipped_items", 0),
            "skipped_details": [],
        }
        skipped_details = stats.get("skipped_details", [])
        if skipped_details:
            summary["skipped_details"] = skipped_details[:50]
        return summary

    def _format_summary_for_job(self, summary: SyncStats) -> str:
        files = summary.get("files_processed", 0) or 0
        deleted = summary.get("files_deleted", 0) or 0
        pages = summary.get("pages_processed", 0) or 0
        folders = summary.get("folders_processed", 0) or 0
        skipped = summary.get("skipped_items", 0) or 0

        processed_parts: list[str] = []
        if files:
            processed_parts.append(f"{files} file{'s' if files != 1 else ''}")
        if deleted:
            processed_parts.append(
                f"{deleted} deleted file{'s' if deleted != 1 else ''}"
            )
        if pages:
            processed_parts.append(f"{pages} page{'s' if pages != 1 else ''}")
        if not processed_parts:
            processed_parts.append("0 files")

        extra_parts: list[str] = []
        if folders:
            extra_parts.append(f"{folders} folder{'s' if folders != 1 else ''} scanned")
        if skipped:
            extra_parts.append(f"{skipped} item{'s' if skipped != 1 else ''} skipped")

        message = "Imported " + ", ".join(processed_parts)
        if extra_parts:
            message = f"{message} ({'; '.join(extra_parts)})"
        return message

    def _is_item_in_folder_scope(
        self,
        item: SharePointItem,
        scope_folder_id: Optional[str],
        scope_folder_path: Optional[str] = None,
        known_subfolder_ids: Optional[set[str]] = None,
        selected_item_type: Optional[str] = None,
    ) -> bool:
        """
        Check if an item is within the scope of a selected folder/file.

        Behavior depends on selected_item_type:
        - "file": Only include the specific file (item.id == scope_folder_id)
        - "folder": Include direct children and all descendants of the folder
        - "site_root" or None: Include all items (no filtering)

        For folder scope, an item is in scope if:
        - It is the selected folder itself, OR
        - Its parent is the scope folder itself, OR
        - Its parentReference.path contains the scope folder path (nested descendant)
        """
        if not scope_folder_id:
            return True

        item_id = item.get("id")

        # If selected_item_type is "file", only include the exact file
        if selected_item_type == "file":
            return item_id == scope_folder_id

        # If selected_item_type is "site_root", include everything
        if selected_item_type == "site_root" or selected_item_type is None:
            return True

        # For "folder" type, check if item is in the folder hierarchy
        if selected_item_type == "folder" and item_id == scope_folder_id:
            return True

        parent_ref = item.get("parentReference", {})
        parent_id = parent_ref.get("id")

        # Direct child of the scope folder
        if parent_id == scope_folder_id:
            return True

        # Child of a previously-seen subfolder in scope (backward compatibility).
        if known_subfolder_ids and parent_id in known_subfolder_ids:
            return True

        # Check nested descendants via parentReference.path
        # Graph API returns paths like "/drives/{id}/root:/Documents/Reports"
        # We match against the stored folder_path (e.g. "/Documents/Reports")
        if scope_folder_path:
            relative_path = self._extract_relative_graph_path(
                parent_ref.get("path", "")
            )

            # Item is in scope if its parent path starts with or equals the folder
            # path. SharePoint paths are case-insensitive and may arrive
            # percent-encoded (e.g. "%20", encoded å/ä/ö), so normalize both sides
            # before comparing — otherwise folders with spaces or non-ASCII names
            # silently fail the scope check and never get indexed.
            normalized_scope = self._normalize_path(scope_folder_path)
            normalized_parent = self._normalize_path(relative_path)
            if normalized_scope and (
                normalized_parent == normalized_scope
                or normalized_parent.startswith(normalized_scope + "/")
            ):
                return True

        return False

    def _folder_path_from_item(self, item: SharePointItem) -> Optional[str]:
        relative_parent_path = self._extract_relative_graph_path(
            item.get("parentReference", {}).get("path", "")
        )
        folder_name = str(item.get("name", "")).strip("/")

        if relative_parent_path == "/":
            return f"/{folder_name}" if folder_name else "/"
        if relative_parent_path:
            return (
                f"{relative_parent_path.rstrip('/')}/{folder_name}"
                if folder_name
                else relative_parent_path
            )
        return None

    @staticmethod
    def _normalize_path(path: str) -> str:
        """Normalize a SharePoint path for case- and encoding-insensitive comparison.

        URL-decodes percent-encoding, normalizes Unicode to NFC (so å/ä/ö in NFC
        vs NFD forms compare equal), strips a trailing slash, and casefolds.
        """
        if not path:
            return ""
        decoded = unquote(path)
        nfc = unicodedata.normalize("NFC", decoded)
        return nfc.rstrip("/").casefold()

    @staticmethod
    def _extract_relative_graph_path(parent_path: str) -> str:
        """Convert Graph parentReference.path to a comparable relative path."""
        if not parent_path:
            return ""
        if ":/" in parent_path:
            return parent_path.split(":", 1)[1]
        if "root:" in parent_path:
            return "/"
        return parent_path

    async def _get_all_sharepoint_files(
        self,
        content_client: SharePointContentClient,
        site_id: str,
    ) -> list[SharePointItem]:
        """
        Recursively collect all file names from SharePoint for comparison with database.
        Returns a flat list of all files (not folders) in the drive, including files in subfolders.

        This is used during delta recovery to accurately detect deleted files.
        """
        all_files: list[SharePointItem] = []

        try:
            # Get default drive for the site
            drive_id = await content_client.get_default_drive_id(site_id=site_id)
            if not drive_id:
                logger.warning(f"Could not get drive ID for site {site_id}")
                return []

            # Recursively collect all files starting from root
            await self._collect_files_recursive(
                content_client=content_client,
                site_id=site_id,
                drive_id=drive_id,
                folder_id=None,  # None means root
                all_files=all_files,
            )

            # Also get site pages
            pages = await content_client.get_site_pages(site_id=site_id)
            if data := pages.get("value", []):
                all_files.extend(self._flatten_files(data))

        except Exception as e:
            logger.error(f"Error getting SharePoint files for comparison: {e}")
            # Return empty list on error - safe default
            return []

        return all_files

    async def _collect_files_recursive(
        self,
        content_client: SharePointContentClient,
        site_id: str,
        drive_id: str,
        folder_id: Optional[str],
        all_files: list[SharePointItem],
    ) -> None:
        """
        Recursively collect all files from a folder and its subfolders.

        Args:
            content_client: The SharePoint client
            site_id: The site ID
            drive_id: The drive ID
            folder_id: The folder ID to collect from (None for root)
            all_files: The list to collect files into (mutated)
        """
        try:
            # Get items in this folder
            if folder_id:
                items = await content_client.get_folder_items(
                    site_id=site_id,
                    drive_id=drive_id,
                    folder_id=folder_id,
                )
            else:
                # Root folder
                items = await content_client.get_documents_in_drive(site_id=site_id)

            for item in items:
                if item.get("folder"):
                    # It's a folder - recurse into it
                    item_id = item.get("id")
                    if item_id:
                        await self._collect_files_recursive(
                            content_client=content_client,
                            site_id=site_id,
                            drive_id=drive_id,
                            folder_id=item_id,
                            all_files=all_files,
                        )
                else:
                    # It's a file - add to our list
                    all_files.append(item)

        except Exception as e:
            logger.warning(f"Error collecting files from folder {folder_id}: {e}")
            # Continue with other folders on error

    def _flatten_files(self, items: list[SharePointItem]) -> list[SharePointItem]:
        """Extract all files from a list of items (excluding folders)."""
        files: list[SharePointItem] = []
        for item in items:
            if not item.get("folder", {}):
                # It's a file
                files.append(item)
        return files

    async def token_refresh_callback(self, token_id: UUID) -> dict[str, str]:
        token = await self.oauth_token_service.refresh_and_update_token(
            token_id=token_id
        )
        return {
            "access_token": token.access_token,
            "refresh_token": token.refresh_token,
        }

    def _get_item_type(self, item: SharePointItem) -> str:
        if item.get("folder"):
            return "folder"

        return file_extension_to_type(item.get("name", ""))

    async def _get_file_content(
        self, client: SharePointContentClient, item: SharePointItem
    ) -> tuple[Optional[str], Optional[str]]:
        item_id = item.get("id")
        item_name = item.get("name", "").lower()
        item_type = self._get_item_type(item)
        drive_id = item.get("parentReference", {}).get("driveId")

        if not item_id or item_type == "folder" or not drive_id:
            return None, None

        skip_reason = unsupported_file_reason(item_name)
        if skip_reason:
            return None, skip_reason

        try:
            content, _ = await client.get_file_content_by_id(
                drive_id=drive_id, item_id=item_id
            )
            if not content:
                return None, "Empty or unreadable content"
            return content, None

        except ValueError as e:
            if "exceeds max download size" in str(e):
                return None, "File too large (exceeds 50 MB limit)"
            logger.error(f"Error getting file content for {item_name}: {e}")
            return None, f"Error: {e}"
        except Exception as e:
            logger.error(f"Error getting file content for {item_name}: {e}")
            return None, f"Error: {e}"
