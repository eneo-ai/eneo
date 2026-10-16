import asyncio
import hashlib
import unicodedata
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal, Optional, cast
from urllib.parse import unquote
from uuid import UUID

import aiohttp
from sqlalchemy import event

from eneo.info_blobs.info_blob import InfoBlobAdd, InfoBlobUpdate, SourceMetadataEntry
from eneo.integration.domain.entities.oauth_token import OauthToken
from eneo.integration.domain.entities.sync_log import SyncLog
from eneo.integration.domain.entities.tenant_sharepoint_app import (
    TenantSharePointApp,
)
from eneo.integration.domain.repositories.integration_knowledge_repo import (
    SyncStateFields,
)
from eneo.integration.infrastructure.clients.sharepoint_content_client import (
    AccessTokenProvider,
    DeltaTokenExpiredException,
    MissingDownloadUrlError,
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
from eneo.integration.infrastructure.content_service.sharepoint_metadata import (
    SharePointColumnCatalog,
    extract_source_metadata,
    source_metadata_fingerprint,
)
from eneo.integration.infrastructure.content_service.types import (
    SharePointItem,
    SharePointTokenProtocol,
    SyncMetadata,
    SyncStats,
)
from eneo.integration.infrastructure.content_service.utils import (
    EMPTY_CONTENT_REASON,
    NO_TEXT_REASONS,
    error_reason,
    file_extension_to_type,
    file_too_large_reason,
    is_unextractable_content,
)
from eneo.integration.infrastructure.office_change_key_service import (
    OfficeChangeKeyService,
)
from eneo.main.config import get_settings
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
    from eneo.integration.domain.repositories.user_integration_repo import (
        UserIntegrationRepository,
    )
    from eneo.integration.infrastructure.auth_service.org_token_provider import (
        OrgTokenProvider,
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

# skipped_details is persisted in last_sync_summary and SyncLog metadata; cap it so
# a library full of unsupported files cannot bloat those rows. skipped_total keeps
# the true count.
_MAX_SKIPPED_DETAILS = 50

# Download failures that say something about the file itself (gone, or closed to
# this identity) rather than about Graph or the network; a pass may move past them.
_ITEM_LEVEL_HTTP_STATUSES = frozenset({403, 404, 410})

# "failed" is an item whose failure was already counted by the delete that failed.
BlobOutcome = Literal["embedded", "unchanged", "empty", "failed"]


class SyncItemsFailed(Exception):
    """A pass that reached its end but could not finish every item.

    Raised after the pass persisted what it could, so the ordinary failure path
    records it; the summary rides along so the failure record keeps the counts
    and the skipped details that name the files.
    """

    def __init__(
        self,
        summary: SyncStats,
        *,
        changes_detected: int | None = None,
        message: str | None = None,
    ):
        failed = summary.get("failed_items", 0)
        super().__init__(
            message
            or f"{failed} file{'s' if failed != 1 else ''} could not be processed; "
            f"the next sync retries {'them' if failed != 1 else 'it'}"
        )
        self.summary = summary
        self.changes_detected = changes_detected


class SyncAccessDenied(SyncItemsFailed):
    """Every download of the pass was refused (HTTP 403).

    One refusal among successes is about that file (a sensitivity label, a
    broken-inheritance folder) and the pass moves past it. When nothing could
    be downloaded the problem is the identity (a conditional access policy, a
    changed Sites.Selected grant), so the pass fails and keeps its token.
    """

    def __init__(
        self, summary: SyncStats, *, forbidden: int, changes_detected: int | None = None
    ):
        super().__init__(
            summary,
            changes_detected=changes_detected,
            message=(
                f"SharePoint refused all {forbidden} "
                f"download{'s' if forbidden != 1 else ''} (HTTP 403); check the "
                "integration's access to this library, the next sync retries "
                f"{'them' if forbidden != 1 else 'it'}"
            ),
        )


class ScopeFolderUnavailable(Exception):
    """Graph could not tell us where the selected folder is right now.

    Raised before any item of a delta pass is classified: the stored path may
    be stale (an ancestor renamed or moved), and classifying against it would
    delete every nested file as out of scope. The pass fails with its token
    kept and is replayed by the next sync.
    """

    def __init__(self, cause: Exception) -> None:
        super().__init__(
            f"Could not read the selected folder from SharePoint: "
            f"{user_visible_error(cause)}"
        )


def _failure_summary(failure: Exception) -> SyncStats | None:
    return failure.summary if isinstance(failure, SyncItemsFailed) else None


def _sync_outcome_fields(knowledge: "IntegrationKnowledge") -> SyncStateFields:
    """The columns a finished pass writes; the entity copy carries the values."""
    return {
        "last_sync_status": knowledge.last_sync_status,
        "last_sync_error": knowledge.last_sync_error,
        "last_synced_at": knowledge.last_synced_at,
        "last_sync_summary": knowledge.last_sync_summary,
        "delta_token": knowledge.delta_token,
    }


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


def _summary_counts(stats: SyncStats) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "files_processed": stats.get("files_processed", 0),
        "files_deleted": stats.get("files_deleted", 0),
        "pages_processed": stats.get("pages_processed", 0),
        "folders_processed": stats.get("folders_processed", 0),
        "unchanged_items": stats.get("unchanged_items", 0),
        "skipped_items": stats.get("skipped_items", 0),
        "skipped_total": stats.get("skipped_total", stats.get("skipped_items", 0)),
        "skipped_truncated": stats.get("skipped_truncated", False),
    }
    if failed_items := stats.get("failed_items", 0):
        summary["failed_items"] = failed_items
    reconcile_warning = stats.get("reconcile_warning")
    if reconcile_warning:
        summary["reconcile_warning"] = reconcile_warning
    return summary


def _delta_worth_logging(summary: SyncStats) -> bool:
    """Delta runs are frequent; only keep the ones that changed something or warned."""
    return (
        summary.get("files_processed", 0) > 0
        or summary.get("files_deleted", 0) > 0
        or summary.get("skipped_items", 0) > 0
        or bool(summary.get("reconcile_warning"))
    )


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
        metadata["unchanged_items"] = stats.get("unchanged_items", 0)
        metadata["skipped_items"] = stats.get("skipped_items", 0)
        metadata["skipped_total"] = stats.get(
            "skipped_total", stats.get("skipped_items", 0)
        )
        metadata["skipped_truncated"] = stats.get("skipped_truncated", False)
        metadata["skipped_details"] = stats.get("skipped_details", [])
        if failed_items := stats.get("failed_items", 0):
            metadata["failed_items"] = failed_items
        reconcile_warning = stats.get("reconcile_warning")
        if reconcile_warning:
            metadata["reconcile_warning"] = reconcile_warning
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
        info_blob_service: "InfoBlobService",
        integration_knowledge_repo: "IntegrationKnowledgeRepository",
        oauth_token_service: "OauthTokenService",
        session: "AsyncSession",
        tenant_sharepoint_app_repo: "TenantSharePointAppRepository",
        tenant_app_auth_service: "TenantAppAuthService",
        service_account_auth_service: "ServiceAccountAuthService | None" = None,
        sync_log_repo: "SyncLogRepository | None" = None,
        change_key_service: "OfficeChangeKeyService | None" = None,
        org_token_provider: "OrgTokenProvider | None" = None,
    ) -> None:
        super().__init__()
        self.org_token_provider = org_token_provider
        self.job_service = job_service
        self.oauth_token_repo = oauth_token_repo
        self.user_integration_repo = user_integration_repo
        self.user = user
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
        # Library column definitions per drive, fetched once per service
        # instance (one sync job). Failed reads are cached as None so a drive
        # whose columns cannot be read is asked only once.
        self._column_catalogs: dict[str, Optional[SharePointColumnCatalog]] = {}

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

    async def _org_access_token(
        self, tenant_app: TenantSharePointApp
    ) -> tuple[str, Optional[AccessTokenProvider]]:
        """An organisation token plus a re-acquire callback for long syncs.

        The provider records credential health and lets the Graph client
        re-acquire on 401; without one (legacy wiring) the token is minted
        once and a sync longer than its lifetime fails.
        """
        if self.org_token_provider is not None:
            access_token = await self.org_token_provider.get_access_token(tenant_app)
            return access_token, self.org_token_provider.access_token_provider(
                tenant_app
            )
        if tenant_app.is_service_account():
            return await self._refresh_service_account_access_token(tenant_app), None
        return await self.tenant_app_auth_service.get_access_token(tenant_app), None

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
                access_token, access_token_provider = await self._org_access_token(
                    tenant_app
                )
                logger.info(
                    "Using %s auth for tenant_app %s",
                    tenant_app.auth_method,
                    tenant_app_id,
                )
                token = SimpleSharePointToken(access_token=access_token)
                oauth_token_id = None
            elif token_id:
                token = await self.oauth_token_repo.one(id=token_id)
                oauth_token_id = token.id
                access_token_provider = None
            else:
                raise ValueError("Either token_id or tenant_app_id must be provided")

            stats = self._initialize_stats()

            integration_knowledge = await self.integration_knowledge_repo.one(
                id=integration_knowledge_id
            )
            resolved_integration_knowledge_id = integration_knowledge.id
            integration_knowledge.mark_sync_started(started_at)
            resolved_site_id = site_id or integration_knowledge.site_id
            resolved_drive_id = drive_id or integration_knowledge.drive_id
            binding: SyncStateFields = {"last_sync_attempted_at": started_at}
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
            await self.integration_knowledge_repo.update_sync_state(
                integration_knowledge.id, **binding
            )

            delta_baseline = await self._pull_content(
                token=_require_sharepoint_token(token),
                oauth_token_id=oauth_token_id,
                integration_knowledge_id=resolved_integration_knowledge_id,
                site_id=resolved_site_id,
                drive_id=resolved_drive_id,
                resource_type=resource_type,
                stats=stats,
                access_token_provider=access_token_provider,
            )
            summary_stats, forbidden = self._summarize_pass(stats)
            # The baseline is not persisted and an existing token is cleared
            # by the failure record: the next sync is a full one and retries
            # the failed files instead of a delta never seeing them again.
            if forbidden:
                raise SyncAccessDenied(summary_stats, forbidden=forbidden)
            if summary_stats.get("failed_items"):
                raise SyncItemsFailed(summary_stats)

            integration_knowledge.last_sync_summary = _summary_counts(summary_stats)
            integration_knowledge.mark_sync_succeeded(datetime.now(timezone.utc))
            if delta_baseline:
                integration_knowledge.delta_token = delta_baseline

            await self.integration_knowledge_repo.update_sync_state(
                integration_knowledge.id, **_sync_outcome_fields(integration_knowledge)
            )

            if self.sync_log_repo:
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

            return self._format_summary_for_job(summary_stats)

        except Exception as e:
            summary = _failure_summary(e)
            await self._record_sync_failure(
                resolved_integration_knowledge_id,
                e,
                sync_type="full",
                started_at=started_at,
                summary=summary,
                metadata=_sync_metadata(
                    summary, trigger=sync_trigger, recovery=recovery
                ),
                clear_delta_token=isinstance(e, SyncItemsFailed),
            )
            logger.error(f"Error in pull_content: {e}", exc_info=True)
            raise

    async def _record_sync_failure(
        self,
        integration_knowledge_id: UUID | None,
        failure: Exception,
        *,
        sync_type: str,
        started_at: datetime,
        metadata: SyncMetadata,
        summary: SyncStats | None = None,
        clear_delta_token: bool = False,
    ) -> None:
        """Persist the failure before re-raising; never raises itself.

        The worker commits on a soft failure (see
        ``_schedule_post_commit_change_keys``), so the status written here is what
        the UI shows. Only the status columns are written, so a rename committed
        during the sync survives. Each write is attempted on its own so a broken
        status row still leaves a sync log, and neither can replace the
        exception being recorded. ``clear_delta_token`` drops the token when a
        full sync could not finish every item: a delta from it would never
        re-emit those items, so the next sync must be a full one.
        """
        if integration_knowledge_id is None:
            return
        error = user_visible_error(failure)
        failed_at = datetime.now(timezone.utc)
        try:
            integration_knowledge = await self.integration_knowledge_repo.one(
                id=integration_knowledge_id
            )
            integration_knowledge.mark_sync_failed(error)
            fields: SyncStateFields = {
                "last_sync_status": integration_knowledge.last_sync_status,
                "last_sync_error": integration_knowledge.last_sync_error,
            }
            if summary is not None:
                integration_knowledge.last_sync_summary = _summary_counts(summary)
                fields["last_sync_summary"] = integration_knowledge.last_sync_summary
            if clear_delta_token:
                integration_knowledge.delta_token = None
                fields["delta_token"] = None
            await self.integration_knowledge_repo.update_sync_state(
                integration_knowledge_id, **fields
            )
        except Exception:
            logger.error(
                "Could not record sync failure on integration knowledge %s",
                integration_knowledge_id,
                exc_info=True,
            )
        if self.sync_log_repo is None:
            return
        try:
            await self.sync_log_repo.add(
                SyncLog(
                    integration_knowledge_id=integration_knowledge_id,
                    sync_type=sync_type,
                    status="error",
                    started_at=started_at,
                    completed_at=failed_at,
                    error_message=error,
                    metadata=metadata,
                )
            )
        except Exception:
            logger.error(
                "Could not write the error sync log for integration knowledge %s",
                integration_knowledge_id,
                exc_info=True,
            )

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

        With ``record_failure`` false a failure of the delta pass itself is only
        raised, not written to the knowledge row: a pending pass that follows a
        successful sync must not turn that sync's status into an error. A full
        sync run as recovery (missing or expired token) is recorded regardless:
        it was attempted, the token it replaces is gone, and the next sync is
        a full one, so its failure is the knowledge's current state.
        """
        started_at = datetime.now(timezone.utc)
        resolved_integration_knowledge_id: UUID | None = integration_knowledge_id
        delegated_to_full_sync = False

        try:
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
                    "Using %s auth for delta sync tenant_app %s",
                    tenant_app.auth_method,
                    tenant_app_id,
                )
                token = SimpleSharePointToken(access_token=access_token)
                oauth_token_id = None
            elif token_id:
                token = await self.oauth_token_repo.one(id=token_id)
                oauth_token_id = token.id
                access_token_provider = None
            else:
                raise ValueError("Either token_id or tenant_app_id must be provided")

            integration_knowledge = await self.integration_knowledge_repo.one(
                id=integration_knowledge_id
            )
            resolved_integration_knowledge_id = integration_knowledge.id
            integration_knowledge.mark_sync_started(started_at)
            await self.integration_knowledge_repo.update_sync_state(
                integration_knowledge.id, last_sync_attempted_at=started_at
            )
            resolved_site_id = site_id or integration_knowledge.site_id
            resolved_drive_id = drive_id or integration_knowledge.drive_id

            if not integration_knowledge.delta_token:
                logger.warning(
                    f"No delta token found for integration knowledge {integration_knowledge_id}, "
                    "falling back to full sync"
                )
                delegated_to_full_sync = True
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
                access_token_provider=access_token_provider,
                include_list_item_fields=True,
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

                if len(changes) == 0:
                    logger.info(
                        f"Delta query returned 0 changes for integration knowledge {integration_knowledge_id}. "
                        "No updates needed - SharePoint is in sync with database."
                    )

                    if new_delta_token:
                        integration_knowledge.delta_token = new_delta_token

                    summary_stats = self._build_summary_stats(stats)

                    integration_knowledge.last_sync_summary = _summary_counts(
                        summary_stats
                    )
                    integration_knowledge.mark_sync_succeeded(
                        datetime.now(timezone.utc)
                    )
                    await self.integration_knowledge_repo.update_sync_state(
                        integration_knowledge.id,
                        **_sync_outcome_fields(integration_knowledge),
                    )

                    logger.info("Delta sync completed: no changes detected")
                    return self._format_summary_for_job(summary_stats)

                logger.info(f"Processing {len(changes)} changed items from delta query")
                # Accumulate processed (item_id, change_key) pairs and write them to
                # the Redis ChangeKey cache only after the DB transaction commits.
                # See _schedule_post_commit_change_keys for why.
                pending_change_keys: list[tuple[UUID, str, str]] = []
                change_ids = {
                    change_id for change in changes if (change_id := change.get("id"))
                }
                scope_folder_id = integration_knowledge.folder_id
                if (
                    integration_knowledge.selected_item_type == "folder"
                    and scope_folder_id
                ):
                    # The stored path goes stale when an ancestor of the scope
                    # folder is renamed or moved: Graph emits the ancestor, not
                    # the unchanged scope folder, so nothing in the changes
                    # carries the new path, and the next change under the folder
                    # would be classified against the stale path and deleted as
                    # out of scope. Read the current path from Graph each pass.
                    # The folder's own delta entry is the second source (Graph
                    # orders entries arbitrarily, so a descendant can precede it).
                    refreshed_scope_path = await self._current_scope_folder_path(
                        content_client, actual_drive_id, scope_folder_id
                    ) or self._scope_folder_path_from_changes(changes, scope_folder_id)
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
                            resolved_integration_knowledge_id,
                            scope_folder_id,
                        )
                        folder_scope_path_unresolved = True

                for item in changes:
                    item_name = item.get("name", "")
                    item_id = item.get("id")
                    is_deleted = has_graph_facet(item, "deleted")
                    is_folder = has_graph_facet(item, "folder")

                    logger.debug(
                        f"  - Item: {item_name} (deleted={is_deleted}, folder={is_folder})"
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
                        and integration_knowledge.selected_item_type == "folder"
                    ):
                        known_subfolder_ids.add(item_id)

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
                        if (
                            integration_knowledge.selected_item_type == "folder"
                            and item_id != integration_knowledge.folder_id
                        ):
                            await self._index_folder_subtree_entering_scope(
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
                                pending_change_keys=pending_change_keys,
                                change_ids=change_ids,
                            )
                        continue

                    await self._sync_changed_file(
                        content_client=content_client,
                        drive_id=actual_drive_id,
                        item=item,
                        integration_knowledge=integration_knowledge,
                        integration_knowledge_id=resolved_integration_knowledge_id,
                        stats=stats,
                        pending_change_keys=pending_change_keys,
                    )

                summary_stats, forbidden = self._summarize_pass(stats)
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
                            changes_detected=len(changes),
                        )
                    raise SyncItemsFailed(summary_stats, changes_detected=len(changes))

                integration_knowledge.delta_token = new_delta_token
                integration_knowledge.last_sync_summary = _summary_counts(summary_stats)
                integration_knowledge.mark_sync_succeeded(datetime.now(timezone.utc))

                logger.info(f"Delta sync completed: {summary_stats}")

                await self.integration_knowledge_repo.update_sync_state(
                    integration_knowledge.id,
                    **_sync_outcome_fields(integration_knowledge),
                )

                self._schedule_post_commit_change_keys(pending_change_keys)

                logger.info(
                    f"Processed {len(changes)} delta changes for integration knowledge {resolved_integration_knowledge_id}"
                )

                if self.sync_log_repo:
                    if _delta_worth_logging(summary_stats):
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
            if delegated_to_full_sync:
                # The full sync recorded the failure and its sync log itself.
                raise
            logger.error(f"Error processing delta changes: {e}", exc_info=True)
            if not record_failure:
                raise
            summary = _failure_summary(e)
            await self._record_sync_failure(
                resolved_integration_knowledge_id,
                e,
                sync_type="delta",
                started_at=started_at,
                summary=summary,
                metadata=_sync_metadata(
                    summary,
                    trigger=sync_trigger,
                    changes_detected=(
                        e.changes_detected if isinstance(e, SyncItemsFailed) else None
                    ),
                ),
            )
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
        access_token_provider: Optional[AccessTokenProvider] = None,
    ) -> str | None:
        """Enumerate and index the scope; returns the delta baseline minted for it.

        The baseline is minted before the first listing: a change made while a
        folder is being enumerated is then replayed by the first delta instead
        of lost until the item changes again (the replay is idempotent through
        the content hash and the ChangeKey cache). The caller persists it with
        the success write only, so a pass that fails leaves the next sync a
        full one. ``None`` when the knowledge already has a token or the mint
        failed.

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
                access_token_provider=access_token_provider,
                include_list_item_fields=True,
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
                    delta_baseline = await self._mint_delta_baseline(
                        content_client, actual_drive_id, integration_knowledge_id
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
                        scope: SyncStateFields = {"selected_item_type": "folder"}
                        if refreshed_folder_path:
                            integration_knowledge.folder_path = refreshed_folder_path
                            scope["folder_path"] = refreshed_folder_path
                        await self.integration_knowledge_repo.update_sync_state(
                            integration_knowledge.id, **scope
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
                        return delta_baseline
                    else:
                        logger.info(
                            f"Processing single file '{item_name}' (ID: {folder_id_value}) "
                            f"for integration knowledge {integration_knowledge_id}"
                        )
                        integration_knowledge.selected_item_type = "file"
                        await self.integration_knowledge_repo.update_sync_state(
                            integration_knowledge.id, selected_item_type="file"
                        )

                        unsupported_reason = unsupported_file_reason(item_name)
                        if unsupported_reason:
                            stats["skipped_items"] += 1
                            stats["skipped_details"].append(
                                {"file": item_name, "reason": unsupported_reason}
                            )
                            return delta_baseline

                        content, skip_reason = await self._extract_file(
                            content_client,
                            actual_drive_id,
                            folder_id_value,
                            item_name,
                            stats,
                        )
                        if content and not is_unextractable_content(content):
                            outcome = await self._process_info_blob(
                                title=item_name,
                                text=content,
                                url=item_info.get("webUrl", ""),
                                integration_knowledge=integration_knowledge,
                                sharepoint_item_id=folder_id_value,
                                source_metadata=await self._source_metadata_for(
                                    content_client,
                                    actual_drive_id,
                                    cast(SharePointItem, item_info),
                                ),
                                stats=stats,
                            )
                            self._count_outcome(stats, outcome, item_name)
                        else:
                            await self._skip_or_remove_unextractable(
                                item_id=folder_id_value,
                                item_name=item_name,
                                skip_reason=skip_reason,
                                integration_knowledge=integration_knowledge,
                                integration_knowledge_id=integration_knowledge_id,
                                stats=stats,
                            )

                        return delta_baseline
                else:
                    integration_knowledge.selected_item_type = "site_root"
                    await self.integration_knowledge_repo.update_sync_state(
                        integration_knowledge.id, selected_item_type="site_root"
                    )

                    # Enumerate the drive the knowledge is bound to; asking Graph for
                    # the site's default drive again would silently diverge from the
                    # drive the delta token and reconciliation operate on.
                    data = await content_client.get_drive_root_children(actual_drive_id)

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
            logger.error(f"Error processing document {site_id}: {e}", exc_info=True)
            raise

        return delta_baseline

    @staticmethod
    async def _mint_delta_baseline(
        content_client: SharePointContentClient,
        drive_id: str,
        integration_knowledge_id: UUID,
    ) -> str | None:
        """A delta token for the drive as it is now; ``None`` when Graph refused."""
        try:
            delta_token = await content_client.initialize_delta_token(drive_id)
        except Exception as e:
            logger.warning(
                "Failed to initialize delta token for integration knowledge %s: %s",
                integration_knowledge_id,
                e,
            )
            return None
        if delta_token:
            logger.info(
                "Initialized delta token for integration knowledge %s",
                integration_knowledge_id,
            )
        return delta_token

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
                if not drive_id or not item_id:
                    continue
                await self._index_listed_file(
                    client=client,
                    drive_id=drive_id,
                    item=document,
                    integration_knowledge=integration_knowledge,
                    stats=stats,
                )

    async def _index_listed_file(
        self,
        *,
        client: SharePointContentClient,
        drive_id: str,
        item: SharePointItem,
        integration_knowledge: "IntegrationKnowledge",
        stats: SyncStats,
    ) -> None:
        """Index one file of a full-sync listing; a failure is counted, not raised."""
        item_name = item.get("name", "")
        item_id = item.get("id")
        try:
            content, skip_reason = await self._get_file_content(client, item, stats)
            if content and not is_unextractable_content(content):
                outcome = await self._process_info_blob(
                    title=item_name,
                    text=content,
                    url=item.get("webUrl", ""),
                    integration_knowledge=integration_knowledge,
                    sharepoint_item_id=item_id,
                    source_metadata=await self._source_metadata_for(
                        client, drive_id, item
                    ),
                    stats=stats,
                )
                self._count_outcome(stats, outcome, item_name)
            else:
                await self._skip_or_remove_unextractable(
                    item_id=item_id,
                    item_name=item_name,
                    skip_reason=skip_reason,
                    integration_knowledge=integration_knowledge,
                    integration_knowledge_id=integration_knowledge.id,
                    stats=stats,
                )
        except Exception as e:
            logger.error(f"Error processing file {item_name}: {e}", exc_info=True)
            self._count_failure(stats, item_name, error_reason(e))

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
            page_name = (
                page.get("name", "") or page.get("title", "") or f"Page {page_id}"
            )
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
                    stats["skipped_items"] += 1
                    stats["skipped_details"].append(
                        {"file": page_name, "reason": EMPTY_CONTENT_REASON}
                    )
                    continue
                outcome = await self._process_info_blob(
                    title=content.get("title", ""),
                    text=page_text,
                    url=content.get("webUrl", ""),
                    integration_knowledge=integration_knowledge,
                    sharepoint_item_id=page_id,
                    stats=stats,
                )
                self._count_outcome(stats, outcome, page_name, page=True)
            except Exception as e:
                logger.error(
                    f"Error processing site page {page_name}: {e}", exc_info=True
                )
                self._count_failure(stats, page_name, error_reason(e))

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

    async def _source_metadata_for(
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
    def _change_key_with_metadata(
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

    async def _process_info_blob(
        self,
        title: str,
        text: str,
        url: str,
        integration_knowledge: "IntegrationKnowledge",
        *,
        stats: SyncStats,
        sharepoint_item_id: Optional[str] = None,
        source_metadata: Optional[list[SourceMetadataEntry]] = None,
    ) -> BlobOutcome:
        sanitized_text = sanitize_text_for_db(text)
        if not sanitized_text.strip():
            # Nothing indexable survives sanitising; treat it like a parser that
            # found no text so a previously indexed copy does not linger. The
            # caller counts the skip from the outcome.
            if sharepoint_item_id:
                deleted = await self._delete_local_sharepoint_item(
                    item_id=sharepoint_item_id,
                    item_name=title,
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

        new_blob_size = safe_int(getattr(info_blob, "size", 0))
        await self._adjust_size(
            integration_knowledge, new_blob_size - previous_blob_size
        )
        return "embedded"

    async def _adjust_size(
        self, integration_knowledge: "IntegrationKnowledge", delta: int
    ) -> None:
        if not delta:
            return
        integration_knowledge.size = await self.integration_knowledge_repo.adjust_size(
            integration_knowledge.id, delta
        )

    @staticmethod
    def _count_outcome(
        stats: SyncStats, outcome: BlobOutcome, item_name: str, *, page: bool = False
    ) -> None:
        if outcome == "embedded":
            stats["pages_processed" if page else "files_processed"] += 1
        elif outcome == "unchanged":
            stats["unchanged_items"] += 1
        elif outcome == "empty":
            stats["skipped_items"] += 1
            stats["skipped_details"].append(
                {"file": item_name, "reason": EMPTY_CONTENT_REASON}
            )

    @staticmethod
    def _count_failure(stats: SyncStats, item_name: str, reason: str) -> None:
        """Count an item the pass could not finish; the pass must not move past it."""
        stats["failed_items"] = stats.get("failed_items", 0) + 1
        stats["skipped_items"] += 1
        stats["skipped_details"].append(
            {"file": item_name, "reason": f"{reason} (retried by the next sync)"}
        )

    async def _delete_local_sharepoint_item(
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
                    safe_int(getattr(blob, "size", 0)) for blob in valid_deleted_blobs
                )
                await self._adjust_size(integration_knowledge, -deleted_size)

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
            self._count_failure(
                stats, item_name, f"Could not remove {reason}: {user_visible_error(e)}"
            )
            return None

    async def _delete_local_blob_for_unextractable_item(
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
        deleted = await self._delete_local_sharepoint_item(
            item_id=item_id,
            item_name=item_name,
            integration_knowledge=integration_knowledge,
            integration_knowledge_id=integration_knowledge_id,
            stats=stats,
            reason="unextractable",
        )
        if deleted is None:
            return
        stats["skipped_items"] += 1
        stats["skipped_details"].append({"file": item_name, "reason": reason})

    @staticmethod
    def _is_positive_unextractable_result(
        content: Optional[str], skip_reason: Optional[str]
    ) -> bool:
        return content is None and skip_reason in NO_TEXT_REASONS

    async def _skip_or_remove_unextractable(
        self,
        *,
        item_id: Optional[str],
        item_name: str,
        skip_reason: Optional[str],
        integration_knowledge: "IntegrationKnowledge",
        integration_knowledge_id: UUID,
        stats: SyncStats,
    ) -> None:
        """Count a file that yielded no text; drop the local copy only for a positive no-text result."""
        if item_id and self._is_positive_unextractable_result(None, skip_reason):
            await self._delete_local_blob_for_unextractable_item(
                item_id=item_id,
                item_name=item_name,
                integration_knowledge=integration_knowledge,
                integration_knowledge_id=integration_knowledge_id,
                stats=stats,
                reason=skip_reason or EMPTY_CONTENT_REASON,
            )
            return
        stats["skipped_items"] += 1
        if skip_reason:
            stats["skipped_details"].append({"file": item_name, "reason": skip_reason})

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
                "the next pass replays the folder",
                folder_name,
                folder_id,
                exc,
            )
            self._count_failure(
                stats,
                folder_name,
                "Could not list folder contents: " + user_visible_error(exc),
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

    async def _current_scope_folder_path(
        self,
        content_client: SharePointContentClient,
        drive_id: str,
        scope_folder_id: str,
    ) -> Optional[str]:
        """The scope folder's path as Graph has it now; ``None`` when the folder is gone.

        Only a 404 is an answer about the folder; any other failure says nothing
        about where it is, so it fails the pass instead of letting the stored
        path, which may be stale, decide what is out of scope.
        """
        try:
            folder_metadata = await content_client.get_file_metadata(
                drive_id=drive_id, item_id=scope_folder_id
            )
        except aiohttp.ClientResponseError as exc:
            if exc.status != 404:
                raise ScopeFolderUnavailable(exc) from exc
            logger.warning(
                "Scope folder %s is gone (404); classifying against the stored path",
                scope_folder_id,
            )
            return None
        except Exception as exc:
            raise ScopeFolderUnavailable(exc) from exc
        return self._folder_path_from_item(cast(SharePointItem, folder_metadata))

    def _scope_folder_path_from_changes(
        self, changes: list[SharePointItem], scope_folder_id: str
    ) -> Optional[str]:
        for item in changes:
            if item.get("id") != scope_folder_id or has_graph_facet(item, "deleted"):
                continue
            return self._folder_path_from_item(item)
        return None

    async def _sync_changed_file(
        self,
        *,
        content_client: SharePointContentClient,
        drive_id: str,
        item: SharePointItem,
        integration_knowledge: "IntegrationKnowledge",
        integration_knowledge_id: UUID,
        stats: SyncStats,
        pending_change_keys: list[tuple[UUID, str, str]],
    ) -> None:
        """Index one changed file; a failure is counted here and fails the pass at its end."""
        item_name = item.get("name", "")
        try:
            item_id = require_text(item.get("id"), "item id")
            source_metadata = await self._source_metadata_for(
                content_client, drive_id, item
            )
            change_key = self._change_key_with_metadata(
                item.get("cTag"), source_metadata, title=item_name
            )

            if self.change_key_service and change_key:
                should_process = await self.change_key_service.should_process(
                    integration_knowledge_id=integration_knowledge_id,
                    item_id=item_id,
                    change_key=change_key,
                )
                if not should_process:
                    logger.info(
                        f"Skipping item {item_name} (ID: {item_id}): ChangeKey already processed (duplicate)"
                    )
                    stats["unchanged_items"] += 1
                    return

            unsupported_reason = unsupported_file_reason(item_name)
            if unsupported_reason:
                stats["skipped_items"] += 1
                stats["skipped_details"].append(
                    {"file": item_name, "reason": unsupported_reason}
                )
                return

            content, skip_reason = await self._extract_file(
                content_client, drive_id, item_id, item_name, stats
            )
            if content and not is_unextractable_content(content):
                outcome = await self._process_info_blob(
                    title=item_name,
                    text=content,
                    url=item.get("webUrl", ""),
                    integration_knowledge=integration_knowledge,
                    sharepoint_item_id=item_id,
                    source_metadata=source_metadata,
                    stats=stats,
                )
                self._count_outcome(stats, outcome, item_name)

                # Defer the ChangeKey cache write until after commit so a
                # rolled-back sync re-processes the item instead of skipping it.
                if self.change_key_service and change_key and outcome != "failed":
                    pending_change_keys.append(
                        (integration_knowledge_id, item_id, change_key)
                    )
            else:
                await self._skip_or_remove_unextractable(
                    item_id=item_id,
                    item_name=item_name,
                    skip_reason=skip_reason,
                    integration_knowledge=integration_knowledge,
                    integration_knowledge_id=integration_knowledge_id,
                    stats=stats,
                )

        except Exception as e:
            logger.error(
                f"Error processing changed file {item_name}: {e}", exc_info=True
            )
            self._count_failure(stats, item_name, error_reason(e))

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
        integration_knowledge_id: UUID,
        stats: SyncStats,
        pending_change_keys: list[tuple[UUID, str, str]],
        change_ids: set[str],
    ) -> None:
        """Index the files of a folder that entered the selected scope.

        Graph re-emits only the moved folder, not its unchanged children, so a
        folder dragged into scope would otherwise never get its files indexed.
        Children that are already indexed (a rename inside scope) or that arrive
        as their own entries in this change set (a freshly created folder) are
        left to the ordinary path.
        """
        try:
            descendants = await self._enumerate_authoritative_items(
                client=content_client,
                resource_type=resource_type,
                site_id=site_id,
                drive_id=drive_id,
                folder_id=folder_id,
            )
            indexed = await self.info_blob_service.repo.get_sharepoint_item_ids_for_integration_knowledge(
                integration_knowledge_id=integration_knowledge_id
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
            self._count_failure(
                stats,
                folder_name,
                "Could not list folder contents: " + user_visible_error(exc),
            )
            return

        indexed_ids = {item_id for _, item_id in indexed}
        for descendant in descendants:
            descendant_id = descendant.get("id")
            if (
                not descendant_id
                or descendant_id in indexed_ids
                or descendant_id in change_ids
            ):
                continue
            await self._sync_changed_file(
                content_client=content_client,
                drive_id=drive_id,
                item=descendant,
                integration_knowledge=integration_knowledge,
                integration_knowledge_id=integration_knowledge_id,
                stats=stats,
                pending_change_keys=pending_change_keys,
            )

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
            event.listen(sync_session, "after_commit", _on_after_commit, once=True)
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
        items = await self._enumerate_authoritative_items(
            client=client,
            resource_type=resource_type,
            site_id=site_id,
            drive_id=drive_id,
            folder_id=folder_id,
        )
        return {item_id for item in items if (item_id := item.get("id"))}

    async def _enumerate_authoritative_items(
        self,
        *,
        client: SharePointContentClient,
        resource_type: str,
        site_id: Optional[str],
        drive_id: str,
        folder_id: Optional[str],
    ) -> list[SharePointItem]:
        """Strictly enumerate every in-scope file (and page) item.

        Listing errors propagate instead of being swallowed: an incomplete
        enumeration must NOT be treated as the authoritative set during
        reconciliation, or it would delete valid blobs.
        """
        items: list[SharePointItem] = []

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
                results = await client.get_drive_root_children(drive_id)
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
                    items.append(item)

        await _walk(folder_id)

        # Site pages live alongside drive documents for site-root SharePoint scopes.
        if resource_type != "onedrive" and site_id and folder_id is None:
            pages = await client.get_site_pages(site_id=site_id)
            items.extend(page for page in pages.get("value", []) if page.get("id"))

        return items

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
                exc_info=True,
            )
            stats["reconcile_warning"] = (
                "Orphan cleanup skipped: could not list SharePoint items "
                f"({user_visible_error(exc)})"
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
            stats["reconcile_warning"] = (
                f"Orphan cleanup skipped: {len(orphans)} of {len(indexed)} indexed "
                f"documents are missing from SharePoint (above the safety cap of {cap})"
            )
            return

        logger.info(
            "Reconciliation removing %d orphaned blob(s) for integration_knowledge %s",
            len(orphans),
            integration_knowledge.id,
        )
        for _blob_id, item_id in orphans:
            await self._delete_local_sharepoint_item(
                item_id=item_id,
                item_name=item_id,
                integration_knowledge=integration_knowledge,
                integration_knowledge_id=integration_knowledge.id,
                stats=stats,
                reason="reconcile-orphan",
            )

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

            if self._get_item_type(item) == "folder":
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

            await self._index_listed_file(
                client=client,
                drive_id=drive_id,
                item=item,
                integration_knowledge=integration_knowledge,
                stats=stats,
            )

    def _initialize_stats(self) -> SyncStats:
        return {
            "files_processed": 0,
            "files_deleted": 0,
            "out_of_scope_deleted": 0,
            "folders_processed": 0,
            "pages_processed": 0,
            "unchanged_items": 0,
            "skipped_items": 0,
            "failed_items": 0,
            "skipped_details": [],
        }

    def _summarize_pass(self, stats: SyncStats) -> tuple[SyncStats, int]:
        """The pass summary, and how many downloads were refused if all of them were.

        Refusals were counted as file-level skips as they came; once the pass
        shows they were the only outcome they become its failures.
        """
        forbidden = 0
        attempts = stats.get("download_attempts", 0)
        if attempts and stats.get("download_forbidden", 0) == attempts:
            forbidden = attempts
            stats["failed_items"] = stats.get("failed_items", 0) + forbidden
        return self._build_summary_stats(stats), forbidden

    def _build_summary_stats(self, stats: SyncStats) -> SyncStats:
        skipped_details = stats.get("skipped_details", [])
        summary: SyncStats = {
            "files_processed": stats.get("files_processed", 0),
            "files_deleted": stats.get("files_deleted", 0),
            "out_of_scope_deleted": stats.get("out_of_scope_deleted", 0),
            "pages_processed": stats.get("pages_processed", 0),
            "folders_processed": stats.get("folders_processed", 0),
            "unchanged_items": stats.get("unchanged_items", 0),
            "skipped_items": stats.get("skipped_items", 0),
            "skipped_total": stats.get("skipped_items", 0),
            "skipped_truncated": len(skipped_details) > _MAX_SKIPPED_DETAILS,
            "skipped_details": [
                {
                    "file": detail["file"],
                    "reason": user_visible_error(detail["reason"]),
                }
                for detail in skipped_details[:_MAX_SKIPPED_DETAILS]
            ],
        }
        if failed_items := stats.get("failed_items", 0):
            summary["failed_items"] = failed_items
        reconcile_warning = stats.get("reconcile_warning")
        if reconcile_warning:
            summary["reconcile_warning"] = user_visible_error(reconcile_warning)
        return summary

    def _format_summary_for_job(self, summary: SyncStats) -> str:
        files = summary.get("files_processed", 0) or 0
        deleted = summary.get("files_deleted", 0) or 0
        pages = summary.get("pages_processed", 0) or 0
        folders = summary.get("folders_processed", 0) or 0
        unchanged = summary.get("unchanged_items", 0) or 0
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
        if unchanged:
            extra_parts.append(f"{unchanged} unchanged")
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
        self, client: SharePointContentClient, item: SharePointItem, stats: SyncStats
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

        return await self._extract_file(client, drive_id, item_id, item_name, stats)

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
        and timeout errors, an item served without a download URL, anything
        unexpected) propagates: it says nothing about the file, so the caller
        must not move past it.
        """
        stats["download_attempts"] = stats.get("download_attempts", 0) + 1
        try:
            result = await client.get_file_extraction_by_id(
                drive_id=drive_id, item_id=item_id
            )
        except MissingDownloadUrlError:
            raise
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
            if e.status not in _ITEM_LEVEL_HTTP_STATUSES:
                raise
            if e.status == 403:
                stats["download_forbidden"] = stats.get("download_forbidden", 0) + 1
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
