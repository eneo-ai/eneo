import asyncio
from typing import TYPE_CHECKING, List, Optional

from intric.integration.domain.entities.integration_preview import IntegrationPreview
from intric.integration.domain.entities.oauth_token import SharePointToken
from intric.integration.infrastructure.clients.sharepoint_content_client import (
    SharePointContentClient,
)
from intric.integration.infrastructure.preview_service.base_preview_service import (
    BasePreviewService,
)
from intric.main.logging import get_logger

if TYPE_CHECKING:
    from intric.integration.domain.repositories.tenant_sharepoint_app_repo import (
        TenantSharePointAppRepository,
    )
    from intric.integration.infrastructure.oauth_token_service import OauthTokenService
    from intric.integration.domain.entities.tenant_sharepoint_app import TenantSharePointApp
    from intric.integration.infrastructure.auth_service.tenant_app_auth_service import TenantAppAuthService
    from intric.integration.infrastructure.auth_service.service_account_auth_service import ServiceAccountAuthService

logger = get_logger(__name__)


class SharePointPreviewService(BasePreviewService):
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

    async def get_preview_info(
        self,
        token: SharePointToken,
    ) -> List[IntegrationPreview]:
        """Get preview information from SharePoint sites and OneDrive (user OAuth)"""

        results: List[IntegrationPreview] = []
        async with SharePointContentClient(
            base_url=token.base_url,
            api_token=token.access_token,
            token_id=token.id,
            token_refresh_callback=self.token_refresh_callback,
        ) as content_client:
            # Get SharePoint sites from all accessible sources
            sites = await self._fetch_all_accessible_sites(content_client)
            results.extend(sites)

            # Get user's OneDrive (only available with user OAuth, not tenant app)
            try:
                drive_data = await content_client.get_my_drive()
                if drive_data:
                    owner = drive_data.get("owner", {}).get("user", {})
                    display_name = owner.get("displayName", "Min enhet")
                    results.append(IntegrationPreview(
                        name=f"OneDrive - {display_name}",
                        key=drive_data.get("id"),
                        url=drive_data.get("webUrl"),
                        type="onedrive",
                    ))
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
                extra={"tenant_app_id": str(tenant_app.id), "auth_method": tenant_app.auth_method}
            )
            token_data = await self.service_account_auth_service.refresh_access_token(tenant_app)
            new_refresh_token = token_data.get("refresh_token")
            if new_refresh_token and new_refresh_token != tenant_app.service_account_refresh_token:
                tenant_app.update_refresh_token(new_refresh_token)
                if self.tenant_sharepoint_app_repo:
                    await self.tenant_sharepoint_app_repo.update(tenant_app)
            access_token = token_data["access_token"]
            logger.info(
                "Service account token refreshed successfully",
                extra={"tenant_app_id": str(tenant_app.id), "token_length": len(access_token) if access_token else 0}
            )
        else:
            if not self.tenant_app_auth_service:
                raise ValueError("TenantAppAuthService not configured")
            access_token = await self.tenant_app_auth_service.get_access_token(tenant_app)
            logger.info(
                "Using tenant app authentication for preview",
                extra={"tenant_app_id": str(tenant_app.id), "auth_method": tenant_app.auth_method}
            )

        # Use the token to fetch sites
        async with SharePointContentClient(
            base_url="https://graph.microsoft.com",
            api_token=access_token,
            token_id=None,  # No token_id for app auth
            token_refresh_callback=None,  # No refresh callback needed for app auth
        ) as content_client:
            if tenant_app.is_service_account():
                # Service account (delegated auth) — combine multiple sources
                return await self._fetch_all_accessible_sites(content_client)
            else:
                # Tenant app (application permissions) — search sees everything
                try:
                    data = await content_client.get_sites()
                except Exception as e:
                    logger.error(f"Error fetching SharePoint preview data with app auth: {e}")
                    raise
                return self._to_sharepoint_preview_data(data=data)

    async def _fetch_all_accessible_sites(
        self,
        content_client: SharePointContentClient,
    ) -> List[IntegrationPreview]:
        """Fetch sites from multiple Graph API sources and deduplicate.

        Combines:
        1. sites?search=* (search-indexed sites)
        2. me/followedSites (sites the user follows)
        3. Group-connected sites (via me/memberOf)

        Each source is best-effort — if one fails the others still return.
        """

        async def _search_sites() -> List[dict]:
            try:
                data = await content_client.get_sites()
                return data.get("value", [])
            except Exception as e:
                logger.warning("Failed to fetch search-indexed sites: %s", e)
                return []

        async def _followed_sites() -> List[dict]:
            try:
                return await content_client.get_followed_sites()
            except Exception as e:
                logger.warning("Failed to fetch followed sites: %s", e)
                return []

        async def _group_sites() -> List[dict]:
            try:
                return await content_client.get_group_connected_sites()
            except Exception as e:
                logger.warning("Failed to fetch group-connected sites: %s", e)
                return []

        search_results, followed_results, group_results = await asyncio.gather(
            _search_sites(), _followed_sites(), _group_sites()
        )

        # Deduplicate on site ID
        seen_ids: set[str] = set()
        unique_sites: List[IntegrationPreview] = []
        for site in (*search_results, *followed_results, *group_results):
            site_id = site.get("id")
            if site_id and site_id not in seen_ids:
                seen_ids.add(site_id)
                unique_sites.append(
                    IntegrationPreview(
                        name=site.get("displayName"),
                        key=site_id,
                        url=site.get("webUrl"),
                        type="site",
                    )
                )

        logger.info(
            "SharePoint preview site discovery completed",
            extra={
                "search_count": len(search_results),
                "followed_count": len(followed_results),
                "group_count": len(group_results),
                "unique_count": len(unique_sites),
            },
        )

        return unique_sites

    def _to_sharepoint_preview_data(
        self,
        data: dict,
    ) -> List[IntegrationPreview]:
        results = data.get("value", [])

        data: List[IntegrationPreview] = []
        for r in results:
            item = IntegrationPreview(
                name=r.get("displayName"),
                key=r.get("id"),
                url=r.get("webUrl"),
                type="site",
            )
            data.append(item)
        return data
