import asyncio
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, cast

from typing_extensions import override

from eneo.integration.domain.entities.integration_preview import IntegrationPreview
from eneo.integration.domain.entities.oauth_token import OauthToken, SharePointToken
from eneo.integration.infrastructure.clients.sharepoint_content_client import (
    SharePointContentClient,
)
from eneo.integration.infrastructure.content_service.types import SharePointItem
from eneo.integration.infrastructure.preview_service.base_preview_service import (
    BasePreviewService,
)
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

logger = get_logger(__name__)


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
    ):
        super().__init__(oauth_token_service)
        self.tenant_app_auth_service = tenant_app_auth_service
        self.service_account_auth_service = service_account_auth_service
        self.tenant_sharepoint_app_repo = tenant_sharepoint_app_repo

    @override
    async def get_preview_info(
        self,
        token: OauthToken,
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
            # Get SharePoint sites
            try:
                sites_data = await content_client.get_sites()
                site_previews = self._to_sharepoint_preview_data(data=sites_data)
                categories = await self._classify_site_categories(
                    content_client=content_client, site_previews=site_previews
                )
                for preview in site_previews:
                    preview.category = categories.get(
                        preview.key, self.CATEGORY_OTHER_SITES
                    )
                results.extend(site_previews)
            except Exception as e:
                logger.error(f"Error fetching SharePoint sites: {e}")
                raise

            # Get user's OneDrive (only available with user OAuth, not tenant app)
            try:
                drive_data = await content_client.get_my_drive()
                if drive_data:
                    owner = drive_data.get("owner", {}).get("user", {})
                    display_name = owner.get("displayName")
                    drive_id = drive_data.get("id")
                    web_url = drive_data.get("webUrl")
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
            except Exception as e:
                # OneDrive may not be available (e.g., permissions not granted)
                logger.warning(f"Could not fetch OneDrive: {e}")

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
                content_client=content_client, site_previews=site_previews
            )
            for preview in site_previews:
                preview.category = categories.get(
                    preview.key, self.CATEGORY_OTHER_SITES
                )

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
        content_client: SharePointContentClient,
        site_previews: List[IntegrationPreview],
    ) -> Dict[str, str]:
        categories = {
            preview.key: self.CATEGORY_OTHER_SITES
            for preview in site_previews
            if preview.key
        }
        if not site_previews:
            return categories

        try:
            teams = await content_client.get_m365_groups()
        except Exception as e:
            logger.warning(
                "Could not classify SharePoint sites by team membership/visibility: %s",
                e,
            )
            return {
                preview.key: self.CATEGORY_UNKNOWN
                for preview in site_previews
                if preview.key
            }

        if not teams:
            return categories

        has_membership_context = True
        try:
            member_group_ids: set[str] = set(
                await content_client.get_my_member_group_ids()
            )
        except Exception as e:
            logger.info(
                "Could not load memberOf groups for SharePoint categorization, "
                "falling back to visibility-only categorization: %s",
                e,
            )
            has_membership_context = False
            member_group_ids = set()

        team_site_map = await self._get_team_site_map(
            content_client=content_client, teams=teams
        )

        for item in team_site_map:
            site_key = self._find_preview_site_key(
                site_previews=site_previews,
                site_id=item.get("site_id"),
                web_url=item.get("web_url"),
            )
            if not site_key:
                continue

            group_id = item.get("group_id")
            if has_membership_context and group_id in member_group_ids:
                categories[site_key] = self.CATEGORY_MY_TEAMS
                continue

            visibility = (item.get("visibility") or "").lower()
            if visibility == "public":
                categories[site_key] = self.CATEGORY_PUBLIC_TEAMS_NOT_MEMBER

        return categories

    async def _get_team_site_map(
        self,
        content_client: SharePointContentClient,
        teams: Sequence[SharePointItem],
    ) -> List[Dict[str, str]]:
        semaphore = asyncio.Semaphore(8)

        async def load_group_site(team: SharePointItem) -> Optional[Dict[str, str]]:
            group_id = team.get("id")
            if not isinstance(group_id, str) or not group_id:
                return None

            async with semaphore:
                site = await content_client.get_group_root_site(group_id=group_id)

            if not site:
                return None

            site_id = site.get("id")
            web_url = site.get("webUrl")
            visibility = team.get("visibility")
            return {
                "group_id": group_id,
                "visibility": visibility if isinstance(visibility, str) else "",
                "site_id": site_id if isinstance(site_id, str) else "",
                "web_url": web_url if isinstance(web_url, str) else "",
            }

        tasks = [load_group_site(team) for team in teams if team.get("id")]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        mapped_sites: List[Dict[str, str]] = []
        for result in results:
            if isinstance(result, BaseException):
                logger.debug(
                    "Failed to load team root site during classification: %s",
                    result,
                )
                continue
            if not result:
                continue
            if not result.get("site_id") and not result.get("web_url"):
                continue
            mapped_sites.append(result)

        return mapped_sites

    def _find_preview_site_key(
        self,
        site_previews: List[IntegrationPreview],
        site_id: Optional[str],
        web_url: Optional[str],
    ) -> Optional[str]:
        if site_id:
            for preview in site_previews:
                if preview.key == site_id:
                    return preview.key

        normalized_target = self._normalize_web_url(web_url)
        if not normalized_target:
            return None

        for preview in site_previews:
            if self._normalize_web_url(preview.url) == normalized_target:
                return preview.key

        return None

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
