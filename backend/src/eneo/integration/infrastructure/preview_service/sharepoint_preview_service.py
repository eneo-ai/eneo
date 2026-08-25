import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, cast
from uuid import UUID

from typing_extensions import override

from eneo.integration.domain.entities.integration_preview import IntegrationPreview
from eneo.integration.domain.entities.oauth_token import OauthToken, SharePointToken
from eneo.integration.infrastructure.clients.sharepoint_content_client import (
    SharePointContentClient,
)
from eneo.integration.infrastructure.preview_service.base_preview_service import (
    BasePreviewService,
)
from eneo.main.config import get_settings
from eneo.main.logging import get_logger

if TYPE_CHECKING:
    from eneo.integration.domain.entities.tenant_sharepoint_app import (
        TenantSharePointApp,
    )
    from eneo.integration.domain.repositories.tenant_sharepoint_app_repo import (
        TenantSharePointAppRepository,
    )
    from eneo.integration.infrastructure.auth_service.service_account_auth_service import (
        ServiceAccountAuthService,
    )
    from eneo.integration.infrastructure.auth_service.tenant_app_auth_service import (
        TenantAppAuthService,
    )
    from eneo.integration.infrastructure.oauth_token_service import OauthTokenService
    from eneo.integration.infrastructure.sharepoint_group_site_cache import (
        SharePointGroupSiteCache,
    )

logger = get_logger(__name__)

# Serve a cached map for its whole TTL, but refresh ahead of expiry so the TTL
# boundary never produces an uncategorized response.
REFRESH_AHEAD_FRACTION = 0.8


class SharePointPreviewService(BasePreviewService):
    CATEGORY_MY_TEAMS = "my_teams"
    CATEGORY_PUBLIC_TEAMS_NOT_MEMBER = "public_teams_not_member"
    CATEGORY_OTHER_SITES = "other_sites"
    CATEGORY_ONEDRIVE = "onedrive"
    CATEGORY_UNKNOWN = "unknown"

    def __init__(
        self,
        oauth_token_service: "OauthTokenService",
        tenant_app_auth_service: Optional["TenantAppAuthService"] = None,
        service_account_auth_service: Optional["ServiceAccountAuthService"] = None,
        tenant_sharepoint_app_repo: Optional["TenantSharePointAppRepository"] = None,
        group_site_cache: Optional["SharePointGroupSiteCache"] = None,
    ):
        super().__init__(oauth_token_service)
        self.tenant_app_auth_service = tenant_app_auth_service
        self.service_account_auth_service = service_account_auth_service
        self.tenant_sharepoint_app_repo = tenant_sharepoint_app_repo
        self.group_site_cache = group_site_cache

    @override
    async def get_preview_info(
        self,
        token: OauthToken,
        tenant_id: Optional[UUID] = None,
    ) -> List[IntegrationPreview]:
        """Get preview information from SharePoint sites and OneDrive (user OAuth)"""

        sharepoint_token = self._require_sharepoint_token(token)
        results: List[IntegrationPreview] = []
        async with SharePointContentClient(
            base_url=sharepoint_token.base_url,
            api_token=sharepoint_token.access_token,
            token_id=sharepoint_token.id,
            token_refresh_callback=self.token_refresh_callback,
        ) as content_client:
            sites_result, member_ids_result, drive_result = await asyncio.gather(
                content_client.get_sites(),
                content_client.get_my_member_group_ids(),
                content_client.get_my_drive(),
                return_exceptions=True,
            )

            if isinstance(sites_result, BaseException):
                logger.error(f"Error fetching SharePoint sites: {sites_result}")
                raise sites_result

            site_previews = self._to_sharepoint_preview_data(data=sites_result)

            member_group_ids: Optional[set[str]] = None
            if isinstance(member_ids_result, BaseException):
                logger.info(
                    "Could not load memberOf groups for SharePoint categorization, "
                    "falling back to visibility-only categorization: %s",
                    member_ids_result,
                )
            else:
                member_group_ids = set(member_ids_result)

            categories = await self._classify_site_categories(
                site_previews=site_previews,
                tenant_id=tenant_id,
                member_group_ids=member_group_ids,
                user_integration_id=token.user_integration.id,
            )
            for preview in site_previews:
                preview.category = categories.get(
                    preview.key, self.CATEGORY_OTHER_SITES
                )
            results.extend(site_previews)

            if isinstance(drive_result, BaseException):
                # OneDrive may not be available (e.g., permissions not granted)
                logger.warning(f"Could not fetch OneDrive: {drive_result}")
            elif drive_result:
                owner = drive_result.get("owner", {}).get("user", {})
                display_name = owner.get("displayName")
                drive_id = drive_result.get("id")
                web_url = drive_result.get("webUrl")
                if isinstance(drive_id, str) and isinstance(web_url, str):
                    results.append(
                        IntegrationPreview(
                            name=(
                                f"OneDrive - {display_name}"
                                if isinstance(display_name, str) and display_name
                                else "OneDrive"
                            ),
                            key=drive_id,
                            url=web_url,
                            type="onedrive",
                            category=self.CATEGORY_ONEDRIVE,
                        )
                    )

        return results

    async def get_preview_info_with_app(
        self,
        tenant_app: "TenantSharePointApp",
    ) -> List[IntegrationPreview]:
        """Get preview information from SharePoint using tenant app credentials"""

        # Get access token based on auth method
        if tenant_app.is_service_account():
            if not self.service_account_auth_service:
                raise ValueError("ServiceAccountAuthService not configured")
            logger.info(
                "Refreshing service account token",
                extra={
                    "tenant_app_id": str(tenant_app.id),
                    "auth_method": tenant_app.auth_method,
                },
            )
            token_data = await self.service_account_auth_service.refresh_access_token(
                tenant_app
            )
            new_refresh_token = token_data.get("refresh_token")
            if (
                new_refresh_token
                and new_refresh_token != tenant_app.service_account_refresh_token
            ):
                tenant_app.update_refresh_token(new_refresh_token)
                if self.tenant_sharepoint_app_repo:
                    await self.tenant_sharepoint_app_repo.update(tenant_app)
            access_token = token_data["access_token"]
            logger.info(
                "Service account token refreshed successfully",
                extra={
                    "tenant_app_id": str(tenant_app.id),
                    "token_length": len(access_token) if access_token else 0,
                },
            )
        else:
            if not self.tenant_app_auth_service:
                raise ValueError("TenantAppAuthService not configured")
            access_token = await self.tenant_app_auth_service.get_access_token(
                tenant_app
            )
            logger.info(
                "Using tenant app authentication for preview",
                extra={
                    "tenant_app_id": str(tenant_app.id),
                    "auth_method": tenant_app.auth_method,
                },
            )

        # Use the token to fetch sites
        data = {}
        async with SharePointContentClient(
            base_url="https://graph.microsoft.com",
            api_token=access_token,
            token_id=None,  # No token_id for app auth
            token_refresh_callback=None,  # No refresh callback needed for app auth
        ) as content_client:
            try:
                data = await content_client.get_sites()
            except Exception as e:
                logger.error(
                    f"Error fetching SharePoint preview data with app auth: {e}"
                )
                raise

        site_previews = self._to_sharepoint_preview_data(data=data)
        categories = await self._classify_site_categories(
            site_previews=site_previews,
            tenant_id=tenant_app.tenant_id,
            member_group_ids=None,
            tenant_app_id=tenant_app.id,
        )
        for preview in site_previews:
            preview.category = categories.get(preview.key, self.CATEGORY_OTHER_SITES)

        return site_previews

    def _to_sharepoint_preview_data(
        self,
        data: Dict[str, Any],
    ) -> List[IntegrationPreview]:
        raw_value = data.get("value", [])
        results: list[Dict[str, Any]] = (
            cast(list[Dict[str, Any]], raw_value) if isinstance(raw_value, list) else []
        )

        previews: List[IntegrationPreview] = []
        for r in results:
            item = IntegrationPreview(
                name=str(r.get("displayName") or ""),
                key=str(r.get("id") or ""),
                url=str(r.get("webUrl") or ""),
                type="site",
                category=self.CATEGORY_OTHER_SITES,
            )
            previews.append(item)
        return previews

    async def _classify_site_categories(
        self,
        *,
        site_previews: List[IntegrationPreview],
        tenant_id: Optional[UUID],
        member_group_ids: Optional[set[str]],
        tenant_app_id: Optional[UUID] = None,
        user_integration_id: Optional[UUID] = None,
    ) -> Dict[str, str]:
        """Categorize sites using the cached per-tenant group->site map.

        Never blocks on Microsoft Graph: a missing or stale map schedules a
        background rebuild and the sites are served uncategorized meanwhile.
        """
        categories = {
            preview.key: self.CATEGORY_OTHER_SITES
            for preview in site_previews
            if preview.key
        }
        if not site_previews or tenant_id is None or self.group_site_cache is None:
            return categories
        if not get_settings().sharepoint_site_categorization_enabled:
            return categories

        try:
            cached = await self.group_site_cache.get(tenant_id)
        except Exception:
            logger.warning(
                "Could not read SharePoint group site map cache",
                extra={"tenant_id": str(tenant_id)},
                exc_info=True,
            )
            return categories

        if cached is None:
            await self.group_site_cache.schedule_rebuild(
                tenant_id,
                tenant_app_id=tenant_app_id,
                user_integration_id=user_integration_id,
            )
            return categories

        entries, built_at = cached
        if self._is_refresh_due(built_at):
            await self.group_site_cache.schedule_rebuild(
                tenant_id,
                tenant_app_id=tenant_app_id,
                user_integration_id=user_integration_id,
            )

        by_site_id = {
            preview.key: preview.key for preview in site_previews if preview.key
        }
        by_url = {
            self._normalize_web_url(preview.url): preview.key
            for preview in site_previews
            if preview.key and preview.url
        }

        for entry in entries:
            site_key = by_site_id.get(entry.get("site_id") or "") or by_url.get(
                self._normalize_web_url(entry.get("web_url"))
            )
            if not site_key:
                continue

            if (
                member_group_ids is not None
                and entry.get("group_id") in member_group_ids
            ):
                categories[site_key] = self.CATEGORY_MY_TEAMS
                continue

            if (entry.get("visibility") or "").lower() == "public":
                categories[site_key] = self.CATEGORY_PUBLIC_TEAMS_NOT_MEMBER

        return categories

    @staticmethod
    def _is_refresh_due(built_at: datetime) -> bool:
        try:
            age_seconds = (datetime.now(timezone.utc) - built_at).total_seconds()
        except TypeError:
            return True
        ttl = get_settings().sharepoint_preview_cache_ttl_seconds
        return age_seconds >= ttl * REFRESH_AHEAD_FRACTION

    @staticmethod
    def _normalize_web_url(url: Optional[str]) -> str:
        if not url:
            return ""
        return url.rstrip("/").lower()

    @staticmethod
    def _require_sharepoint_token(token: OauthToken) -> SharePointToken:
        if not isinstance(token, SharePointToken):
            raise ValueError("Expected a SharePoint token")
        return token
