from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import UUID

import sqlalchemy as sa

from intric.embedding_models.infrastructure.datastore import Datastore
from intric.database.tables.info_blob_chunk_table import InfoBlobChunks
from intric.info_blobs.info_blob import InfoBlobAdd
from intric.integration.domain.entities.oauth_token import SharePointToken
from intric.integration.domain.entities.sync_log import SyncLog
from intric.integration.infrastructure.clients.sharepoint_content_client import (
    SharePointContentClient,
)
from intric.integration.infrastructure.content_service.utils import (
    file_extension_to_type,
)
from intric.main.logging import get_logger

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
    from intric.integration.infrastructure.oauth_token_service import (
        OauthTokenService,
    )
    from intric.jobs.job_service import JobService
    from intric.users.user import UserInDB


logger = get_logger(__name__)


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
        sync_log_repo: "SyncLogRepository" = None,
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
        self.sync_log_repo = sync_log_repo

    async def pull_content(
        self,
        token_id: UUID,
        integration_knowledge_id: UUID,
        site_id: str,
    ) -> str:
        # Start logging the sync
        sync_log = None
        started_at = datetime.now(timezone.utc)

        try:
            token = await self.oauth_token_repo.one(id=token_id)
            stats = self._initialize_stats()

            await self._pull_content(
                token=token,
                integration_knowledge_id=integration_knowledge_id,
                site_id=site_id,
                stats=stats,
            )
            summary_stats = self._build_summary_stats(stats)

            integration_knowledge = await self.integration_knowledge_repo.one(
                id=integration_knowledge_id
            )
            if not getattr(integration_knowledge, "site_id", None):
                integration_knowledge.site_id = site_id
            integration_knowledge.last_sync_summary = summary_stats
            integration_knowledge.last_synced_at = datetime.now(timezone.utc)

            # Initialize delta token if this is the first sync
            if not integration_knowledge.delta_token:
                try:
                    async with SharePointContentClient(
                        base_url=token.base_url,
                        api_token=token.access_token,
                        token_id=token.id,
                        token_refresh_callback=self.token_refresh_callback,
                    ) as content_client:
                        drive_id = await content_client.get_default_drive_id(site_id)
                        if drive_id:
                            delta_token = await content_client.initialize_delta_token(drive_id)
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

            # Log successful sync
            if self.sync_log_repo:
                sync_log = SyncLog(
                    integration_knowledge_id=integration_knowledge_id,
                    sync_type="full",
                    status="success",
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc),
                    metadata=summary_stats,
                )
                await self.sync_log_repo.add(sync_log)

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
        token_id: UUID,
        integration_knowledge_id: UUID,
        site_id: str,
    ) -> str:
        """
        Process incremental changes using the delta token.
        This is called by the webhook handler to efficiently sync only changed items.

        Args:
            token_id: OAuth token ID
            integration_knowledge_id: Integration knowledge ID
            site_id: SharePoint site ID

        Returns:
            Summary of changes processed
        """
        # Start logging the sync
        started_at = datetime.now(timezone.utc)

        try:
            token = await self.oauth_token_repo.one(id=token_id)
            integration_knowledge = await self.integration_knowledge_repo.one(
                id=integration_knowledge_id
            )

            # If no delta token exists, fall back to full sync
            if not integration_knowledge.delta_token:
                logger.warning(
                    f"No delta token found for integration knowledge {integration_knowledge_id}, "
                    "falling back to full sync"
                )
                return await self.pull_content(
                    token_id=token_id,
                    integration_knowledge_id=integration_knowledge_id,
                    site_id=site_id,
                )

            stats = self._initialize_stats()

            async with SharePointContentClient(
                base_url=token.base_url,
                api_token=token.access_token,
                token_id=token.id,
                token_refresh_callback=self.token_refresh_callback,
            ) as content_client:
                drive_id = await content_client.get_default_drive_id(site_id)
                if not drive_id:
                    logger.error(f"Could not get drive ID for site {site_id}")
                    return "Error: Could not find drive"

                # Get delta changes since last sync
                logger.info(
                    f"Starting delta sync with token: {integration_knowledge.delta_token[:20]}..."
                    if integration_knowledge.delta_token else "No delta token"
                )
                changes, new_delta_token = await content_client.get_delta_changes(
                    drive_id=drive_id,
                    delta_token=integration_knowledge.delta_token,
                )
                logger.info(
                    f"Delta query returned {len(changes)} items. New token: {new_delta_token[:20] if new_delta_token else 'None'}..."
                )

                # If we get 0 changes, check if it's due to an invalid delta token
                # by comparing current SharePoint files with database
                if len(changes) == 0:
                    logger.warning(
                        f"Delta query returned 0 changes for integration knowledge {integration_knowledge_id}. "
                        "Checking if delta token is invalid by comparing with current SharePoint state..."
                    )

                    # Get current list of files from SharePoint
                    sharepoint_files = await self._get_all_sharepoint_files(
                        content_client=content_client,
                        site_id=site_id
                    )
                    sharepoint_file_names = {f.get("name") for f in sharepoint_files}

                    # Get current list of files in database for this integration
                    db_blobs = await self.info_blob_service.repo.get_by_filter_integration_knowledge(
                        integration_knowledge_id=integration_knowledge_id
                    )
                    db_file_names = {blob.title for blob in db_blobs}

                    # Find deleted files (in DB but not in SharePoint)
                    deleted_files = db_file_names - sharepoint_file_names

                    if deleted_files:
                        logger.info(f"Found {len(deleted_files)} deleted files: {deleted_files}")
                        # Delete the missing files from database
                        for filename in deleted_files:
                            deleted_blobs = await self.info_blob_service.repo.delete_by_title_and_integration_knowledge(
                                title=filename,
                                integration_knowledge_id=integration_knowledge_id,
                            )
                            for blob in deleted_blobs:
                                if blob is not None:
                                    integration_knowledge.size -= blob.size
                                    stats["files_deleted"] += 1

                    # Update stats with actual current count from database
                    total_blobs = await self.info_blob_service.repo.get_count_by_integration_knowledge(
                        integration_knowledge_id
                    )

                    summary_stats = {
                        "files_processed": total_blobs,
                        "files_deleted": stats.get("files_deleted", 0),
                        "pages_processed": 0,
                        "folders_processed": 0,
                        "skipped_items": 0,
                    }

                    # Reset delta token so next sync will do a fresh initialization
                    integration_knowledge.delta_token = None
                    integration_knowledge.last_sync_summary = summary_stats
                    integration_knowledge.last_synced_at = datetime.now(timezone.utc)
                    await self.integration_knowledge_repo.update(obj=integration_knowledge)

                    logger.info(f"Delta sync completed with recovery: {summary_stats}")
                    return self._format_summary_for_job(summary_stats)

                # Process each changed item
                logger.info(f"Processing {len(changes)} changed items from delta query")
                for item in changes:
                    item_name = item.get("name", "")
                    is_deleted = item.get("deleted", False)
                    is_folder = item.get("folder", False)

                    logger.debug(f"  - Item: {item_name} (deleted={is_deleted}, folder={is_folder})")

                    # Check if item was deleted
                    if is_deleted:
                        # Delete the corresponding info_blob if it exists
                        try:
                            deleted_blobs = await self.info_blob_service.repo.delete_by_title_and_integration_knowledge(
                                title=item_name,
                                integration_knowledge_id=integration_knowledge.id,
                            )

                            # Update integration knowledge size to reflect deletion
                            # Filter out None values before accessing blob.size
                            valid_deleted_blobs = [blob for blob in deleted_blobs if blob is not None]
                            for blob in valid_deleted_blobs:
                                integration_knowledge.size -= blob.size

                            logger.info(f"Deleted {len(valid_deleted_blobs)} info_blob(s) for removed SharePoint file: {item_name}")
                            stats["files_deleted"] = stats.get("files_deleted", 0) + len(valid_deleted_blobs)
                        except Exception as e:
                            logger.warning(
                                f"Could not delete info_blob for {item_name}: {e}"
                            )
                            stats["skipped_items"] += 1
                        continue

                    # Check if it's a folder or file
                    if item.get("folder"):
                        stats["folders_processed"] += 1
                        # For folders, we don't need to do anything - their contents
                        # will be in the delta changes if they changed
                        continue

                    # Process changed/added file
                    # The smart update logic in _process_info_blob will automatically
                    # delete the old version with the same title before adding the new one
                    item_id = item.get("id")
                    web_url = item.get("webUrl", "")

                    try:
                        content, _ = await content_client.get_file_content_by_id(
                            drive_id=drive_id,
                            item_id=item_id,
                        )

                        if content:
                            await self._process_info_blob(
                                title=item_name,
                                text=content,
                                url=web_url,
                                integration_knowledge=integration_knowledge,
                            )
                            stats["files_processed"] += 1
                        else:
                            stats["skipped_items"] += 1

                    except Exception as e:
                        logger.error(f"Error processing changed file {item_name}: {e}")
                        stats["skipped_items"] += 1

                # Update integration knowledge with new delta token and sync info
                integration_knowledge.delta_token = new_delta_token
                integration_knowledge.last_synced_at = datetime.now(timezone.utc)

                # For delta sync, show the number of items actually processed, not total count
                # This gives users insight into what changed, not the entire library
                summary_stats = {
                    "files_processed": stats.get("files_processed", 0),
                    "files_deleted": stats.get("files_deleted", 0),
                    "pages_processed": stats.get("pages_processed", 0),
                    "folders_processed": stats.get("folders_processed", 0),
                    "skipped_items": stats.get("skipped_items", 0),
                }
                integration_knowledge.last_sync_summary = summary_stats
                logger.info(f"Delta sync completed: {summary_stats}")

                await self.integration_knowledge_repo.update(obj=integration_knowledge)

                logger.info(
                    f"Processed {len(changes)} delta changes for integration knowledge {integration_knowledge_id}"
                )

                # Log successful delta sync
                if self.sync_log_repo:
                    sync_log = SyncLog(
                        integration_knowledge_id=integration_knowledge_id,
                        sync_type="delta",
                        status="success",
                        started_at=started_at,
                        completed_at=datetime.now(timezone.utc),
                        metadata=summary_stats,
                    )
                    await self.sync_log_repo.add(sync_log)

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
            # On error, don't update delta token - we'll retry from same position
            raise

    async def _pull_content(
        self,
        token: "SharePointToken",
        integration_knowledge_id: UUID,
        site_id: str,
        stats: Dict[str, int],
    ) -> Dict[str, int]:
        """
        Process a document by its ID. First checks if it's a file or folder,
        then processes accordingly.

        Args:
            token: SharePoint token for authentication
            integration_knowledge_id: ID of the integration knowledge object
            site_id: The SharePoint site ID to process
        """
        integration_knowledge = await self.integration_knowledge_repo.one(
            id=integration_knowledge_id
        )

        try:
            async with SharePointContentClient(
                base_url=token.base_url,
                api_token=token.access_token,
                token_id=token.id,
                token_refresh_callback=self.token_refresh_callback,
            ) as content_client:
                # Documents, include folders
                documents = await content_client.get_documents_in_drive(site_id=site_id)
                if data := documents.get("value", []):
                    await self._process_documents(
                        documents=data,
                        client=content_client,
                        integration_knowledge=integration_knowledge,
                        token=token,
                        stats=stats,
                    )

                # Site pages
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
        stats: Dict[str, int],
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
                    client=client,
                    token=token,
                    integration_knowledge_id=integration_knowledge.id,
                    folder_id=item_id,
                    processed_items=processed_items,
                    stats=stats,
                )
            else:
                # file
                content, _ = await client.get_file_content_by_id(drive_id=drive_id, item_id=item_id)
                if content:
                    await self._process_info_blob(
                        title=document.get("name", ""),
                        text=content,
                        url=document.get("webUrl", ""),
                        integration_knowledge=integration_knowledge,
                    )
                    stats["files_processed"] += 1
                else:
                    stats["skipped_items"] += 1

    async def _process_pages(
        self,
        pages: list,
        client: SharePointContentClient,
        integration_knowledge: "IntegrationKnowledge",
        stats: Dict[str, int],
    ):
        for page in pages:
            site_id = page.get("parentReference", {}).get("siteId")
            content = await client.get_page_content(site_id=site_id, page_id=page.get("id"))
            if content:
                await self._process_info_blob(
                    title=content.get("title", ""),
                    text=content.get("description", ""),
                    url=content.get("webUrl", ""),
                    integration_knowledge=integration_knowledge,
                )
                stats["pages_processed"] += 1
            else:
                stats["skipped_items"] += 1

    async def _process_info_blob(
        self,
        title: str,
        text: str,
        url: str,
        integration_knowledge: "IntegrationKnowledge",
    ) -> None:
        info_blob_add = InfoBlobAdd(
            title=title,
            user_id=self.user.id,
            text=text,
            group_id=None,
            url=url,
            website_id=None,
            tenant_id=self.user.tenant_id,
            integration_knowledge_id=integration_knowledge.id,
        )

        # Use idempotent upsert to handle duplicate webhooks from Microsoft
        # If blob exists, update it; otherwise create new
        # InfoBlobService will calculate size via quota_service
        info_blob = await self.info_blob_service.upsert_info_blob_by_title_and_integration(
            info_blob_add
        )

        # Delete old chunks if this was an update (to avoid duplicates)
        try:
            await self.info_blob_service.repo.session.execute(
                sa.delete(InfoBlobChunks).where(
                    InfoBlobChunks.info_blob_id == info_blob.id
                )
            )
            logger.debug(f"Cleared old chunks for {title}")
        except Exception as e:
            logger.warning(f"Could not delete old chunks for {title}: {e}")

        # Add new embeddings (always, since text may have changed)
        try:
            await self.datastore.add(
                info_blob=info_blob, embedding_model=integration_knowledge.embedding_model
            )
        except Exception as e:
            # If embedding fails, log and continue
            logger.debug(f"Could not add embedding for {title}: {e}")

        # Update integration knowledge size
        integration_knowledge_size = integration_knowledge.size + info_blob.size
        integration_knowledge.size = integration_knowledge_size
        await self.integration_knowledge_repo.update(obj=integration_knowledge)

    async def _fetch_and_process_content(
        self,
        site_id: str,
        drive_id: str,
        token: "SharePointToken",
        integration_knowledge_id: UUID,
        client: SharePointContentClient,
        stats: Dict[str, int],
        folder_id: Optional[str] = None,
        processed_items: set = None,
    ):
        if processed_items is None:
            processed_items = set()

        results = await client.get_folder_items(
            site_id=site_id, drive_id=drive_id, folder_id=folder_id
        )

        if not results:
            return

        await self._process_folder_results(
            site_id=site_id,
            drive_id=drive_id,
            client=client,
            results=results,
            integration_knowledge_id=integration_knowledge_id,
            token=token,
            processed_items=processed_items,
            stats=stats,
        )

    async def _process_folder_results(
        self,
        site_id: str,
        drive_id: str,
        client: SharePointContentClient,
        results: List[Dict[str, Any]],
        integration_knowledge_id: UUID,
        token: "SharePointToken",
        processed_items: set,
        stats: Dict[str, int],
    ) -> None:
        integration_knowledge = await self.integration_knowledge_repo.one(
            id=integration_knowledge_id
        )
        integration_knowledge_size = integration_knowledge.size

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
                await self._fetch_and_process_content(
                    site_id=site_id,
                    drive_id=drive_id,
                    client=client,
                    token=token,
                    integration_knowledge_id=integration_knowledge_id,
                    folder_id=item_id,
                    processed_items=processed_items,
                    stats=stats,
                )
                continue

            content = await self._get_file_content(token, item)

            if content:
                async with self.session.begin_nested():
                    info_blob_add = InfoBlobAdd(
                        title=item_name,
                        user_id=self.user.id,
                        text=content,
                        group_id=None,
                        url=web_url,
                        website_id=None,
                        tenant_id=self.user.tenant_id,
                        integration_knowledge_id=integration_knowledge_id,
                    )

                    info_blob = await self.info_blob_service.add_info_blob_without_validation(
                        info_blob_add
                    )
                    await self.datastore.add(
                        info_blob=info_blob, embedding_model=integration_knowledge.embedding_model
                    )

                    integration_knowledge_size += info_blob.size
                    stats["files_processed"] += 1
            else:
                stats["skipped_items"] += 1

        integration_knowledge.size = integration_knowledge_size
        await self.integration_knowledge_repo.update(obj=integration_knowledge)

    def _initialize_stats(self) -> Dict[str, int]:
        return {
            "files_processed": 0,
            "files_deleted": 0,
            "folders_processed": 0,
            "pages_processed": 0,
            "skipped_items": 0,
        }

    def _build_summary_stats(self, stats: Dict[str, int]) -> Dict[str, int]:
        return {
            "files_processed": stats.get("files_processed", 0),
            "files_deleted": stats.get("files_deleted", 0),
            "pages_processed": stats.get("pages_processed", 0),
            "folders_processed": stats.get("folders_processed", 0),
            "skipped_items": stats.get("skipped_items", 0),
        }

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
            processed_parts.append(f"{deleted} deleted file{'s' if deleted != 1 else ''}")
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

    async def _get_all_sharepoint_files(
        self,
        content_client: SharePointContentClient,
        site_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Recursively collect all file names from SharePoint for comparison with database.
        Returns a flat list of all files (not folders) in the drive.
        """
        all_files = []

        try:
            # Get all documents in the drive
            documents = await content_client.get_documents_in_drive(site_id=site_id)
            if data := documents.get("value", []):
                all_files.extend(self._flatten_files(data))

            # Also get site pages
            pages = await content_client.get_site_pages(site_id=site_id)
            if data := pages.get("value", []):
                all_files.extend(self._flatten_files(data))

        except Exception as e:
            logger.error(f"Error getting SharePoint files for comparison: {e}")
            # Return empty list on error - safe default
            return []

        return all_files

    def _flatten_files(self, items: list[dict]) -> List[Dict[str, Any]]:
        """Extract all files from a list of items (excluding folders)."""
        files = []
        for item in items:
            if not item.get("folder", {}):
                # It's a file
                files.append(item)
            # Note: We don't recursively process folders here since we're just
            # collecting names for comparison. The full sync would handle recursion.
        return files

    async def token_refresh_callback(self, token_id: UUID) -> Dict[str, str]:
        token = await self.oauth_token_service.refresh_and_update_token(token_id=token_id)
        return {
            "access_token": token.access_token,
            "refresh_token": token.refresh_token,
        }

    def _get_item_type(self, item: Dict[str, Any]) -> str:
        if item.get("folder"):
            return "folder"

        return file_extension_to_type(item.get("name", ""))

    async def _get_file_content(
        self, token: "SharePointToken", item: Dict[str, Any]
    ) -> Optional[str]:
        item_id = item.get("id")
        item_name = item.get("name", "").lower()
        item_type = self._get_item_type(item)
        drive_id = item.get("parentReference", {}).get("driveId")

        if not item_id or item_type == "folder" or not drive_id:
            return None

        try:
            async with SharePointContentClient(
                base_url=token.base_url,
                api_token=token.access_token,
                token_id=token.id,
                token_refresh_callback=self.token_refresh_callback,
            ) as content_client:
                content, _ = await content_client.get_file_content_by_id(
                    drive_id=drive_id, item_id=item_id
                )
                return content

        except Exception as e:
            logger.error(f"Error getting file content for {item_name}: {e}")
            return
