import asyncio
from typing import TYPE_CHECKING, Any, Dict, List, Optional, cast

from typing_extensions import override

from eneo.integration.domain.entities.integration_preview import IntegrationPreview
from eneo.integration.domain.entities.oauth_token import OauthToken, SharePointToken
from eneo.integration.infrastructure.clients.sharepoint_content_client import (
    SharePointContentClient,
)
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

# Categorization is garnish, not payload: if Graph throttles the team-site
# lookups, drop it for this request instead of stalling the dialog on
# Retry-After sleeps.
CATEGORIZATION_TIMEOUT_SECONDS = 8.0


class SharePointPreviewService(BasePreviewService):
    CATEGORY_MY_TEAMS = "my_teams"
    CATEGORY_OTHER_SITES = "other_sites"
    CATEGORY_ONEDRIVE = "onedrive"

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

            member_group_ids: Optional[list[str]] = None
            if isinstance(member_ids_result, BaseException):
                logger.info(
                    "Could not load memberOf groups; skipping my-teams "
                    "categorization: %s",
                    member_ids_result,
                )
            else:
                member_group_ids = member_ids_result

            categories = await self._categorize_my_team_sites(
                content_client=content_client,
                site_previews=site_previews,
                member_group_ids=member_group_ids,
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

        # Use the token to fetch sites. Client-credential auth has no /me, so
        # my-teams categorization is not possible here; sites are uncategorized.
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

        return self._to_sharepoint_preview_data(data=data)

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

    async def _categorize_my_team_sites(
        self,
        *,
        content_client: SharePointContentClient,
        site_previews: List[IntegrationPreview],
        member_group_ids: Optional[list[str]],
    ) -> Dict[str, str]:
        """Mark sites backed by the user's own M365 groups as my_teams.

        Only the user's own memberOf groups (typically tens) are resolved, via
        $batch — never the tenant's full group list.
        """
        categories = {
            preview.key: self.CATEGORY_OTHER_SITES
            for preview in site_previews
            if preview.key
        }
        if not site_previews or not member_group_ids:
            return categories

        try:
            site_map = await asyncio.wait_for(
                content_client.get_group_root_sites_batched(member_group_ids),
                timeout=CATEGORIZATION_TIMEOUT_SECONDS,
            )
        except Exception as e:
            logger.warning(
                "Could not resolve team sites for my-teams categorization: %s",
                e if str(e) else type(e).__name__,
            )
            return categories

        by_site_id = {
            preview.key: preview.key for preview in site_previews if preview.key
        }
        by_url = {
            self._normalize_web_url(preview.url): preview.key
            for preview in site_previews
            if preview.key and preview.url
        }

        for site in site_map.values():
            site_key = by_site_id.get(site.get("id") or "") or by_url.get(
                self._normalize_web_url(site.get("webUrl"))
            )
            if site_key:
                categories[site_key] = self.CATEGORY_MY_TEAMS

        return categories

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
