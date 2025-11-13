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
    from intric.integration.infrastructure.oauth_token_service import OauthTokenService
    from intric.integration.domain.entities.tenant_sharepoint_app import TenantSharePointApp
    from intric.integration.infrastructure.auth_service.tenant_app_auth_service import TenantAppAuthService

logger = get_logger(__name__)


class SharePointPreviewService(BasePreviewService):
    def __init__(
        self,
        oauth_token_service: "OauthTokenService",
        tenant_app_auth_service: Optional["TenantAppAuthService"] = None,
    ):
        super().__init__(oauth_token_service)
        self.tenant_app_auth_service = tenant_app_auth_service

    async def get_preview_info(
        self,
        token: SharePointToken,
    ) -> List[IntegrationPreview]:
        """Get preview information from SharePoint: listing all sites (user OAuth)"""

        data = {}
        async with SharePointContentClient(
            base_url=token.base_url,
            api_token=token.access_token,
            token_id=token.id,
            token_refresh_callback=self.token_refresh_callback,
        ) as content_client:
            try:
                data = await content_client.get_sites()
            except Exception as e:
                logger.error(f"Error fetching SharePoint preview data: {e}")
                raise

        return self._to_sharepoint_preview_data(data=data)

    async def get_preview_info_with_app(
        self,
        tenant_app: "TenantSharePointApp",
    ) -> List[IntegrationPreview]:
        """Get preview information from SharePoint using tenant app credentials"""

        if not self.tenant_app_auth_service:
            raise ValueError("TenantAppAuthService not configured")

        # Get access token using tenant app credentials
        access_token = await self.tenant_app_auth_service.get_access_token(tenant_app)

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
                logger.error(f"Error fetching SharePoint preview data with app auth: {e}")
                raise

        return self._to_sharepoint_preview_data(data=data)

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
