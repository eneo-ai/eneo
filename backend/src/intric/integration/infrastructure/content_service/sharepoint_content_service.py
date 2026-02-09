from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple
from uuid import UUID

import sqlalchemy as sa

from intric.embedding_models.infrastructure.datastore import Datastore
from intric.database.tables.info_blob_chunk_table import InfoBlobChunks
from intric.info_blobs.info_blob import InfoBlobAdd
from intric.integration.domain.entities.oauth_token import SharePointToken
from intric.integration.domain.entities.sync_log import SyncLog
from intric.integration.infrastructure.clients.sharepoint_content_client import (
    DeltaTokenExpiredException,
    SharePointContentClient,
)
from intric.integration.infrastructure.content_service.utils import (
    file_extension_to_type,
)
from intric.integration.infrastructure.office_change_key_service import (
    OfficeChangeKeyService,
)
from intric.main.logging import get_logger

from html2text import html2text


def _extract_text_from_canvas_layout(content: dict) -> str:
    """Extract plain text from a SharePoint page's canvasLayout structure.

    Parses horizontalSections and verticalSection to find textWebPart
    elements and converts their innerHtml to plain text.
    """
    texts = []
    canvas = content.get("canvasLayout", {})
    if not canvas:
        return ""

    def _extract_from_webparts(webparts: list):
        for wp in webparts:
            if wp.get("@odata.type") == "#microsoft.graph.textWebPart":
                inner_html = wp.get("innerHtml", "")
                if inner_html:
                    texts.append(html2text(inner_html).strip())

    for section in canvas.get("horizontalSections", []):
        for column in section.get("columns", []):
            _extract_from_webparts(column.get("webparts", []))

    vertical = canvas.get("verticalSection")
    if vertical:
        _extract_from_webparts(vertical.get("webparts", []))

    return "\n\n".join(texts)


def sanitize_text_for_db(text: str) -> str:
    """Remove null bytes and other invalid characters that PostgreSQL doesn't accept.

    PostgreSQL TEXT columns cannot contain null bytes (0x00) in UTF-8 encoding.
    This commonly happens when PDF extraction fails or returns binary data.
    """
    if not text:
        return text
    # Remove null bytes which cause "invalid byte sequence for encoding UTF8: 0x00"
    return text.replace("\x00", "")


def _safe_int(value: Any) -> int:
    """Best-effort int conversion for defensive size accounting."""
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if not isinstance(value, str):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


if TYPE_CHECKING:
    from intric.database.database import AsyncSession
    from intric.info_blobs.info_blob_service import InfoBlobService
    from intric.integration.domain.entities.integration_knowledge import (
        IntegrationKnowledge,
    )
    from intric.integration.domain.repositories.integration_knowledge_repo import (
        IntegrationKnowledgeRepository,
    )
    from intric.integration.domain.repositories.oauth_token_repo import (
        OauthTokenRepository,
    )
    from intric.integration.domain.repositories.sync_log_repo import (
        SyncLogRepository,
    )
    from intric.integration.domain.repositories.user_integration_repo import (
        UserIntegrationRepository,
    )
    from intric.integration.domain.repositories.tenant_sharepoint_app_repo import (
        TenantSharePointAppRepository,
    )
    from intric.integration.infrastructure.auth_service.tenant_app_auth_service import (
        TenantAppAuthService,
    )
    from intric.integration.infrastructure.auth_service.service_account_auth_service import (
        ServiceAccountAuthService,
    )
    from intric.integration.infrastructure.oauth_token_service import (
        OauthTokenService,
    )
    from intric.jobs.job_service import JobService
    from intric.users.user import UserInDB


logger = get_logger(__name__)

# File extensions that cannot produce useful text content.
# These are skipped before download to save bandwidth and avoid database pollution.
_UNSUPPORTED_EXTENSIONS: frozenset[str] = frozenset({
    # Images
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".ico", ".webp", ".tiff", ".tif",
    ".heic", ".heif", ".raw", ".cr2", ".nef", ".arw", ".psd",
    # Video
    ".mp4", ".avi", ".mov", ".wmv", ".mkv", ".webm", ".flv", ".m4v",
    # Audio
    ".mp3", ".wav", ".ogg", ".flac", ".aac", ".wma", ".m4a",
    # Archives
    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2",
    # Executables / binaries
    ".exe", ".dll", ".msi", ".bin", ".iso",
    # Other non-text
    ".ttf", ".otf", ".woff", ".woff2",
})


def _unsupported_file_reason(filename: str) -> Optional[str]:
    """Return a skip reason if the file type is unsupported, or None if OK."""
    name = filename.lower()
    for ext in _UNSUPPORTED_EXTENSIONS:
        if name.endswith(ext):
            # Determine a human-readable category
            if ext in {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".ico", ".webp", ".tiff", ".tif",
                       ".heic", ".heif", ".raw", ".cr2", ".nef", ".arw", ".psd"}:
                return "Unsupported file type (image)"
            if ext in {".mp4", ".avi", ".mov", ".wmv", ".mkv", ".webm", ".flv", ".m4v"}:
                return "Unsupported file type (video)"
            if ext in {".mp3", ".wav", ".ogg", ".flac", ".aac", ".wma", ".m4a"}:
                return "Unsupported file type (audio)"
            return f"Unsupported file type ({ext})"
    return None


class SimpleSharePointToken:
    """Simple token wrapper for SharePoint API calls.

    Used for tenant_app integrations where we don't have an OauthToken
    in the database, but need a token object with access_token attribute.
    """

    def __init__(self, access_token: str):
        self.access_token = access_token


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
        service_account_auth_service: "ServiceAccountAuthService" = None,
        sync_log_repo: "SyncLogRepository" = None,
        change_key_service: "OfficeChangeKeyService" = None,
    ):
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

    async def _refresh_service_account_access_token(self, tenant_app) -> str:
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
        integration_knowledge_id: UUID = None,
        site_id: str = None,
        drive_id: Optional[str] = None,
        folder_id: Optional[str] = None,
        folder_path: Optional[str] = None,
        resource_type: str = "site",
    ) -> str:
        sync_log = None
        started_at = datetime.now(timezone.utc)

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
                token=token,
                oauth_token_id=oauth_token_id,
                integration_knowledge_id=integration_knowledge_id,
                site_id=site_id,
                drive_id=drive_id,
                resource_type=resource_type,
                stats=stats,
            )
            summary_stats = self._build_summary_stats(stats)

            integration_knowledge = await self.integration_knowledge_repo.one(
                id=integration_knowledge_id
            )

            files_processed = summary_stats.get("files_processed", 0)
            files_deleted = summary_stats.get("files_deleted", 0)

            integration_knowledge.last_sync_summary = summary_stats
            if files_processed > 0 or files_deleted > 0:
                integration_knowledge.last_synced_at = datetime.now(timezone.utc)

            if not integration_knowledge.delta_token:
                try:
                    base_url = getattr(token, "base_url", "https://graph.microsoft.com")
                    async with SharePointContentClient(
                        base_url=base_url,
                        api_token=token.access_token,
                        token_id=oauth_token_id,
                        token_refresh_callback=(
                            self.token_refresh_callback if oauth_token_id else None
                        ),
                    ) as content_client:
                        actual_drive_id = drive_id
                        if not actual_drive_id and site_id:
                            actual_drive_id = await content_client.get_default_drive_id(
                                site_id
                            )
                        if actual_drive_id:
                            delta_token = await content_client.initialize_delta_token(
                                actual_drive_id
                            )
                            if delta_token:
                                integration_knowledge.delta_token = delta_token
                                logger.info(
                                    f"Initialized delta token for integration knowledge {integration_knowledge_id}"
                                )
                except Exception as e:
                    logger.warning(
                        f"Failed to initialize delta token for integration knowledge {integration_knowledge_id}: {e}"
                    )

            await self.integration_knowledge_repo.update(obj=integration_knowledge)

            if self.sync_log_repo:
                files_processed = summary_stats.get("files_processed", 0)
                files_deleted = summary_stats.get("files_deleted", 0)
                skipped_items = summary_stats.get("skipped_items", 0)

                if files_processed > 0 or files_deleted > 0 or skipped_items > 0:
                    sync_log = SyncLog(
                        integration_knowledge_id=integration_knowledge_id,
                        sync_type="full",
                        status="success",
                        started_at=started_at,
                        completed_at=datetime.now(timezone.utc),
                        metadata=summary_stats,
                    )
                    await self.sync_log_repo.add(sync_log)
                else:
                    logger.info(
                        f"Skipping sync log creation for integration knowledge {integration_knowledge_id}: "
                        "no files processed or deleted"
                    )

            return self._format_summary_for_job(summary_stats)

        except Exception as e:
            # Log failed sync
            if self.sync_log_repo:
                sync_log = SyncLog(
                    integration_knowledge_id=integration_knowledge_id,
                    sync_type="full",
                    status="error",
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc),
                    error_message=str(e),
                )
                await self.sync_log_repo.add(sync_log)

            logger.error(f"Error in pull_content: {e}")
            raise

    async def process_delta_changes(
        self,
        token_id: Optional[UUID] = None,
        tenant_app_id: Optional[UUID] = None,
        integration_knowledge_id: UUID = None,
        site_id: str = None,
        drive_id: Optional[str] = None,
        resource_type: str = "site",
    ) -> str:
        started_at = datetime.now(timezone.utc)

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

            if not integration_knowledge.delta_token:
                logger.warning(
                    f"No delta token found for integration knowledge {integration_knowledge_id}, "
                    "falling back to full sync"
                )
                return await self.pull_content(
                    token_id=token_id,
                    tenant_app_id=tenant_app_id,
                    integration_knowledge_id=integration_knowledge_id,
                    site_id=site_id,
                    drive_id=drive_id or integration_knowledge.drive_id,
                    resource_type=resource_type
                    or integration_knowledge.resource_type
                    or "site",
                )

            stats = self._initialize_stats()

            base_url = getattr(token, "base_url", "https://graph.microsoft.com")
            async with SharePointContentClient(
                base_url=base_url,
                api_token=token.access_token,
                token_id=oauth_token_id,
                token_refresh_callback=(
                    self.token_refresh_callback if oauth_token_id else None
                ),
            ) as content_client:
                actual_drive_id = drive_id or integration_knowledge.drive_id
                if not actual_drive_id and site_id:
                    actual_drive_id = await content_client.get_default_drive_id(site_id)
                if not actual_drive_id:
                    logger.error(f"Could not get drive ID for site {site_id}")
                    return "Error: Could not find drive"

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
                        integration_knowledge_id,
                    )
                    integration_knowledge.delta_token = None
                    await self.integration_knowledge_repo.update(
                        obj=integration_knowledge
                    )
                    return await self.pull_content(
                        token_id=token_id,
                        tenant_app_id=tenant_app_id,
                        integration_knowledge_id=integration_knowledge_id,
                        site_id=site_id,
                        drive_id=drive_id or integration_knowledge.drive_id,
                        resource_type=resource_type
                        or integration_knowledge.resource_type
                        or "site",
                    )
                logger.info(
                    f"Delta query returned {len(changes)} items. New token: {new_delta_token[:20] if new_delta_token else 'None'}..."
                )

                scope_folder_path = integration_knowledge.folder_path
                known_subfolder_ids: set[str] = set()
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
                        relative_parent_path = self._extract_relative_graph_path(
                            folder_metadata.get("parentReference", {}).get("path", "")
                        )
                        folder_name = str(folder_metadata.get("name", "")).strip("/")

                        if relative_parent_path == "/":
                            resolved_folder_path = (
                                f"/{folder_name}" if folder_name else "/"
                            )
                        elif relative_parent_path:
                            resolved_folder_path = (
                                f"{relative_parent_path.rstrip('/')}/{folder_name}"
                                if folder_name
                                else relative_parent_path
                            )
                        else:
                            resolved_folder_path = None

                        if resolved_folder_path:
                            scope_folder_path = resolved_folder_path
                            integration_knowledge.folder_path = resolved_folder_path
                            await self.integration_knowledge_repo.update(
                                obj=integration_knowledge
                            )
                    except Exception as exc:
                        logger.warning(
                            "Could not resolve folder_path for delta scope (integration_knowledge=%s, folder_id=%s): %s",
                            integration_knowledge_id,
                            integration_knowledge.folder_id,
                            exc,
                        )

                if len(changes) == 0:
                    logger.info(
                        f"Delta query returned 0 changes for integration knowledge {integration_knowledge_id}. "
                        "No updates needed - SharePoint is in sync with database."
                    )

                    if new_delta_token:
                        integration_knowledge.delta_token = new_delta_token

                    summary_stats = {
                        "files_processed": 0,
                        "files_deleted": 0,
                        "pages_processed": 0,
                        "folders_processed": 0,
                        "skipped_items": 0,
                    }

                    integration_knowledge.last_sync_summary = summary_stats
                    await self.integration_knowledge_repo.update(
                        obj=integration_knowledge
                    )

                    logger.info("Delta sync completed: no changes detected")
                    return self._format_summary_for_job(summary_stats)

                logger.info(f"Processing {len(changes)} changed items from delta query")
                for item in changes:
                    item_name = item.get("name", "")
                    item_id = item.get("id")
                    is_deleted = item.get("deleted", False)
                    is_folder = item.get("folder", False)
                    change_key = item.get("cTag")

                    logger.debug(
                        f"  - Item: {item_name} (deleted={is_deleted}, folder={is_folder}, changeKey={change_key})"
                    )

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
                        logger.debug(
                            f"  - Skipping item {item_name}: not in folder scope"
                        )
                        continue

                    if (
                        is_folder
                        and item_id
                        and integration_knowledge.selected_item_type == "folder"
                    ):
                        known_subfolder_ids.add(item_id)

                    if is_deleted:
                        # Delete the corresponding info_blob if it exists
                        try:
                            if item_id:
                                deleted_blobs = await self.info_blob_service.repo.delete_by_sharepoint_item_and_integration_knowledge(
                                    sharepoint_item_id=item_id,
                                    integration_knowledge_id=integration_knowledge.id,
                                )
                            else:
                                deleted_blobs = await self.info_blob_service.repo.delete_by_title_and_integration_knowledge(
                                    title=item_name,
                                    integration_knowledge_id=integration_knowledge.id,
                                )

                            # Update integration knowledge size to reflect deletion
                            # Filter out None values before accessing blob.size
                            valid_deleted_blobs = [
                                blob for blob in deleted_blobs if blob is not None
                            ]
                            if valid_deleted_blobs:
                                current_size = _safe_int(
                                    getattr(integration_knowledge, "size", 0)
                                )
                                deleted_size = sum(
                                    _safe_int(getattr(blob, "size", 0))
                                    for blob in valid_deleted_blobs
                                )
                                integration_knowledge.size = max(
                                    0, current_size - deleted_size
                                )

                            logger.info(
                                "Deleted %s info_blob(s) for removed SharePoint file: %s (item_id=%s)",
                                len(valid_deleted_blobs),
                                item_name,
                                item_id,
                            )
                            stats["files_deleted"] = stats.get(
                                "files_deleted", 0
                            ) + len(valid_deleted_blobs)

                            # Invalidate ChangeKey cache for deleted item
                            if self.change_key_service and item_id:
                                await self.change_key_service.invalidate_change_key(
                                    integration_knowledge_id=integration_knowledge_id,
                                    item_id=item_id,
                                )
                        except Exception as e:
                            logger.warning(
                                f"Could not delete info_blob for {item_name}: {e}"
                            )
                            stats["skipped_items"] += 1
                            stats["skipped_details"].append(
                                {"file": item_name, "reason": f"Could not remove: {e}"}
                            )
                        continue

                    if item.get("folder"):
                        stats["folders_processed"] += 1
                        continue

                    should_process = True
                    if self.change_key_service and item_id and change_key:
                        should_process = await self.change_key_service.should_process(
                            integration_knowledge_id=integration_knowledge_id,
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

                    unsupported_reason = _unsupported_file_reason(item_name)
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

                        if content:
                            await self._process_info_blob(
                                title=item_name,
                                text=content,
                                url=web_url,
                                integration_knowledge=integration_knowledge,
                                sharepoint_item_id=item_id,
                            )
                            stats["files_processed"] += 1

                            # Update ChangeKey cache after successful processing
                            if self.change_key_service and item_id and change_key:
                                await self.change_key_service.update_change_key(
                                    integration_knowledge_id=integration_knowledge_id,
                                    item_id=item_id,
                                    change_key=change_key,
                                )
                        else:
                            stats["skipped_items"] += 1
                            stats["skipped_details"].append(
                                {"file": item_name, "reason": "Empty or unreadable content"}
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
                integration_knowledge.last_sync_summary = summary_stats

                files_processed = summary_stats.get("files_processed", 0)
                files_deleted = summary_stats.get("files_deleted", 0)
                if files_processed > 0 or files_deleted > 0:
                    integration_knowledge.last_synced_at = datetime.now(timezone.utc)

                logger.info(f"Delta sync completed: {summary_stats}")

                await self.integration_knowledge_repo.update(obj=integration_knowledge)

                logger.info(
                    f"Processed {len(changes)} delta changes for integration knowledge {integration_knowledge_id}"
                )

                if self.sync_log_repo:
                    files_processed = summary_stats.get("files_processed", 0)
                    files_deleted = summary_stats.get("files_deleted", 0)
                    skipped_items = summary_stats.get("skipped_items", 0)

                    if files_processed > 0 or files_deleted > 0 or skipped_items > 0:
                        sync_log = SyncLog(
                            integration_knowledge_id=integration_knowledge_id,
                            sync_type="delta",
                            status="success",
                            started_at=started_at,
                            completed_at=datetime.now(timezone.utc),
                            metadata=summary_stats,
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
            if self.sync_log_repo:
                sync_log = SyncLog(
                    integration_knowledge_id=integration_knowledge_id,
                    sync_type="delta",
                    status="error",
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc),
                    error_message=str(e),
                )
                await self.sync_log_repo.add(sync_log)

            logger.error(f"Error processing delta changes: {e}")
            raise

    async def _pull_content(
        self,
        token,
        oauth_token_id: Optional[UUID],
        integration_knowledge_id: UUID,
        site_id: Optional[str],
        drive_id: Optional[str],
        resource_type: str,
        stats: Dict[str, Any],
    ) -> Dict[str, Any]:
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
            base_url = getattr(token, "base_url", "https://graph.microsoft.com")
            async with SharePointContentClient(
                base_url=base_url,
                api_token=token.access_token,
                token_id=oauth_token_id,
                token_refresh_callback=(
                    self.token_refresh_callback if oauth_token_id else None
                ),
            ) as content_client:
                actual_drive_id = drive_id
                if not actual_drive_id and site_id:
                    actual_drive_id = await content_client.get_default_drive_id(site_id)

                if not actual_drive_id:
                    raise ValueError(
                        "Could not determine drive_id - need either drive_id or site_id"
                    )

                if integration_knowledge.folder_id:
                    item_info = await content_client.get_file_metadata(
                        drive_id=actual_drive_id,
                        item_id=integration_knowledge.folder_id,
                    )

                    is_folder = item_info.get("folder") is not None
                    item_name = item_info.get("name", "")

                    if is_folder:
                        logger.info(
                            f"Processing folder '{item_name}' (ID: {integration_knowledge.folder_id}) "
                            f"for integration knowledge {integration_knowledge_id}"
                        )
                        integration_knowledge.selected_item_type = "folder"
                        processed_items = set()
                        await self._fetch_and_process_content(
                            site_id=site_id,
                            drive_id=actual_drive_id,
                            resource_type=resource_type,
                            client=content_client,
                            token=token,
                            integration_knowledge_id=integration_knowledge_id,
                            folder_id=integration_knowledge.folder_id,
                            processed_items=processed_items,
                            stats=stats,
                            is_root_call=True,
                        )
                        return stats
                    else:
                        logger.info(
                            f"Processing single file '{item_name}' (ID: {integration_knowledge.folder_id}) "
                            f"for integration knowledge {integration_knowledge_id}"
                        )
                        integration_knowledge.selected_item_type = "file"

                        unsupported_reason = _unsupported_file_reason(item_name)
                        if unsupported_reason:
                            stats["skipped_items"] += 1
                            stats["skipped_details"].append(
                                {"file": item_name, "reason": unsupported_reason}
                            )
                            return stats

                        content, _ = await content_client.get_file_content_by_id(
                            drive_id=actual_drive_id,
                            item_id=integration_knowledge.folder_id,
                        )

                        if content:
                            await self._process_info_blob(
                                title=item_name,
                                text=content,
                                url=item_info.get("webUrl", ""),
                                integration_knowledge=integration_knowledge,
                                sharepoint_item_id=integration_knowledge.folder_id,
                            )
                            stats["files_processed"] += 1
                        else:
                            stats["skipped_items"] += 1
                            stats["skipped_details"].append(
                                {"file": item_name, "reason": "Empty or unreadable content"}
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
                            site_id=site_id
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

                    if resource_type != "onedrive" and site_id:
                        pages = await content_client.get_site_pages(site_id=site_id)
                        if data := pages.get("value", []):
                            await self._process_pages(
                                pages=data,
                                client=content_client,
                                integration_knowledge=integration_knowledge,
                                stats=stats,
                            )

        except Exception as e:
            logger.error(f"Error processing document {site_id}: {e}")
            raise

        return stats

    async def _process_documents(
        self,
        documents: list[dict],
        client: SharePointContentClient,
        integration_knowledge: "IntegrationKnowledge",
        token: "SharePointToken",
        resource_type: str,
        stats: Dict[str, Any],
    ):
        for document in documents:
            drive_id = document.get("parentReference", {}).get("driveId")
            site_id = document.get("parentReference", {}).get("siteId")
            item_id = document.get("id")
            if document.get("folder", {}):
                stats["folders_processed"] += 1
                # Recursively process all items in the folder
                processed_items = set()
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
                doc_name = document.get("name", "")
                unsupported_reason = _unsupported_file_reason(doc_name)
                if unsupported_reason:
                    stats["skipped_items"] += 1
                    stats["skipped_details"].append(
                        {"file": doc_name, "reason": unsupported_reason}
                    )
                    continue
                content, _ = await client.get_file_content_by_id(
                    drive_id=drive_id, item_id=item_id
                )
                if content:
                    await self._process_info_blob(
                        title=doc_name,
                        text=content,
                        url=document.get("webUrl", ""),
                        integration_knowledge=integration_knowledge,
                        sharepoint_item_id=item_id,
                    )
                    stats["files_processed"] += 1
                else:
                    stats["skipped_items"] += 1
                    stats["skipped_details"].append(
                        {"file": doc_name, "reason": "Empty or unreadable content"}
                    )

    async def _process_pages(
        self,
        pages: list,
        client: SharePointContentClient,
        integration_knowledge: "IntegrationKnowledge",
        stats: Dict[str, Any],
    ):
        for page in pages:
            site_id = page.get("parentReference", {}).get("siteId")
            content = await client.get_page_content(
                site_id=site_id, page_id=page.get("id")
            )
            if content:
                page_text = _extract_text_from_canvas_layout(content)
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
                page_name = page.get("name", "") or page.get("title", "") or f"Page {page.get('id', 'unknown')}"
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

        previous_blob_size = _safe_int(existing_blob.size) if existing_blob else 0

        info_blob_add = InfoBlobAdd(
            title=title,
            user_id=self.user.id,
            text=sanitize_text_for_db(text),
            group_id=None,
            url=url,
            website_id=None,
            tenant_id=self.user.tenant_id,
            integration_knowledge_id=integration_knowledge.id,
            sharepoint_item_id=sharepoint_item_id,
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

        current_size = _safe_int(getattr(integration_knowledge, "size", 0))
        new_blob_size = _safe_int(getattr(info_blob, "size", 0))
        size_delta = new_blob_size - previous_blob_size
        if size_delta:
            integration_knowledge.size = max(0, current_size + size_delta)
            await self.integration_knowledge_repo.update(obj=integration_knowledge)

    async def _fetch_and_process_content(
        self,
        site_id: Optional[str],
        drive_id: str,
        resource_type: str,
        token: "SharePointToken",
        integration_knowledge_id: UUID,
        client: SharePointContentClient,
        stats: Dict[str, Any],
        folder_id: Optional[str] = None,
        processed_items: set = None,
        is_root_call: bool = True,
    ):
        if processed_items is None:
            processed_items = set()

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
        results: List[Dict[str, Any]],
        integration_knowledge_id: UUID,
        token: "SharePointToken",
        processed_items: set,
        stats: Dict[str, Any],
        is_root_call: bool = True,
    ) -> None:
        integration_knowledge = await self.integration_knowledge_repo.one(
            id=integration_knowledge_id
        )

        for item in results:
            item_id = item.get("id")

            if item_id in processed_items:
                continue

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

            if content:
                await self._process_info_blob(
                    title=item_name,
                    text=content,
                    url=web_url,
                    integration_knowledge=integration_knowledge,
                    sharepoint_item_id=item_id,
                )
                stats["files_processed"] += 1
            else:
                stats["skipped_items"] += 1
                if skip_reason:
                    stats["skipped_details"].append(
                        {"file": item_name, "reason": skip_reason}
                    )

    def _initialize_stats(self) -> Dict[str, Any]:
        return {
            "files_processed": 0,
            "files_deleted": 0,
            "folders_processed": 0,
            "pages_processed": 0,
            "skipped_items": 0,
            "skipped_details": [],
        }

    def _build_summary_stats(self, stats: Dict[str, Any]) -> Dict[str, Any]:
        summary: Dict[str, Any] = {
            "files_processed": stats.get("files_processed", 0),
            "files_deleted": stats.get("files_deleted", 0),
            "pages_processed": stats.get("pages_processed", 0),
            "folders_processed": stats.get("folders_processed", 0),
            "skipped_items": stats.get("skipped_items", 0),
        }
        skipped_details = stats.get("skipped_details", [])
        if skipped_details:
            summary["skipped_details"] = skipped_details[:50]
        return summary

    def _format_summary_for_job(self, summary: Dict[str, int]) -> str:
        files = summary.get("files_processed", 0) or 0
        deleted = summary.get("files_deleted", 0) or 0
        pages = summary.get("pages_processed", 0) or 0
        folders = summary.get("folders_processed", 0) or 0
        skipped = summary.get("skipped_items", 0) or 0

        processed_parts = []
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

        extra_parts = []
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
        item: Dict[str, Any],
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
        - Its parent is the scope folder itself, OR
        - Its parentReference.path contains the scope folder path (nested descendant)
        """
        if not scope_folder_id:
            return True

        # If selected_item_type is "file", only include the exact file
        if selected_item_type == "file":
            item_id = item.get("id")
            return item_id == scope_folder_id

        # If selected_item_type is "site_root", include everything
        if selected_item_type == "site_root" or selected_item_type is None:
            return True

        # For "folder" type, check if item is in the folder hierarchy
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

            # Item is in scope if its parent path starts with or equals the folder path
            normalized_scope = scope_folder_path.rstrip("/")
            normalized_parent = relative_path.rstrip("/")
            if normalized_scope and (
                normalized_parent == normalized_scope
                or normalized_parent.startswith(normalized_scope + "/")
            ):
                return True

        return False

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
    ) -> List[Dict[str, Any]]:
        """
        Recursively collect all file names from SharePoint for comparison with database.
        Returns a flat list of all files (not folders) in the drive, including files in subfolders.

        This is used during delta recovery to accurately detect deleted files.
        """
        all_files = []

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
        all_files: List[Dict[str, Any]],
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

    def _flatten_files(self, items: list[dict]) -> List[Dict[str, Any]]:
        """Extract all files from a list of items (excluding folders)."""
        files = []
        for item in items:
            if not item.get("folder", {}):
                # It's a file
                files.append(item)
        return files

    async def token_refresh_callback(self, token_id: UUID) -> Dict[str, str]:
        token = await self.oauth_token_service.refresh_and_update_token(
            token_id=token_id
        )
        return {
            "access_token": token.access_token,
            "refresh_token": token.refresh_token,
        }

    def _get_item_type(self, item: Dict[str, Any]) -> str:
        if item.get("folder"):
            return "folder"

        return file_extension_to_type(item.get("name", ""))

    async def _get_file_content(
        self, client: SharePointContentClient, item: Dict[str, Any]
    ) -> Tuple[Optional[str], Optional[str]]:
        item_id = item.get("id")
        item_name = item.get("name", "").lower()
        item_type = self._get_item_type(item)
        drive_id = item.get("parentReference", {}).get("driveId")

        if not item_id or item_type == "folder" or not drive_id:
            return None, None

        skip_reason = _unsupported_file_reason(item_name)
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
