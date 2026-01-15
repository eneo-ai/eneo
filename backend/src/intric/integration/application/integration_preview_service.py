from typing import TYPE_CHECKING, List, Optional
from uuid import UUID

from intric.integration.domain.entities.integration_preview import IntegrationPreview
from intric.main.logging import get_logger

if TYPE_CHECKING:
    from intric.integration.domain.repositories.oauth_token_repo import (
        OauthTokenRepository,
    )
    from intric.integration.domain.repositories.user_integration_repo import (
        UserIntegrationRepository,
    )
    from intric.integration.domain.repositories.tenant_sharepoint_app_repo import (
        TenantSharePointAppRepository,
    )
    from intric.integration.infrastructure.preview_service.confluence_preview_service import (
        ConfluencePreviewService,
    )
    from intric.integration.infrastructure.preview_service.sharepoint_preview_service import (
        SharePointPreviewService,
    )


logger = get_logger(__name__)


class IntegrationPreviewService:
    def __init__(
        self,
        oauth_token_repo: "OauthTokenRepository",
        user_integration_repo: "UserIntegrationRepository",
        confluence_preview_service: "ConfluencePreviewService",
        sharepoint_preview_service: "SharePointPreviewService",
        tenant_sharepoint_app_repo: Optional["TenantSharePointAppRepository"] = None,
    ):
        self.oauth_token_repo = oauth_token_repo
        self.user_integration_repo = user_integration_repo
        self.confluence_preview_service = confluence_preview_service
        self.sharepoint_preview_service = sharepoint_preview_service
        self.tenant_sharepoint_app_repo = tenant_sharepoint_app_repo

    async def get_preview_data(
        self,
        user_integration_id: UUID,
    ) -> List[IntegrationPreview]:
        user_integration = await self.user_integration_repo.one_or_none(id=user_integration_id)

        if user_integration:
            if not user_integration.authenticated:
                return []

            if user_integration.auth_type == "tenant_app":
                if not self.tenant_sharepoint_app_repo:
                    raise ValueError("Tenant SharePoint app repository not configured")

                if not user_integration.tenant_app_id:
                    raise ValueError(f"Tenant app not found for integration {user_integration_id}")

                tenant_app = await self.tenant_sharepoint_app_repo.get_by_id(
                    user_integration.tenant_app_id
                )
                if tenant_app and tenant_app.is_active:
                    logger.info(
                        "Using tenant app authentication for preview",
                        extra={
                            "user_integration_id": str(user_integration_id),
                            "tenant_app_id": str(user_integration.tenant_app_id),
                            "auth_type": user_integration.auth_type,
                        }
                    )
                    return await self.sharepoint_preview_service.get_preview_info_with_app(
                        tenant_app=tenant_app
                    )
                raise ValueError(f"Tenant app not active for integration {user_integration_id}")

            token = await self.oauth_token_repo.one(user_integration_id=user_integration_id)

            logger.info(
                "Using user OAuth authentication for preview",
                extra={
                    "user_integration_id": str(user_integration_id),
                    "token_type": str(token.token_type),
                    "auth_type": user_integration.auth_type,
                }
            )

            if token.token_type.is_confluence:
                return await self.confluence_preview_service.get_preview_info(
                    token=token
                )
            elif token.token_type.is_sharepoint:
                return await self.sharepoint_preview_service.get_preview_info(
                    token=token
                )
            else:
                raise ValueError(f"Unsupported integration type: {token.token_type}")

        # If not found, check if it's a tenant_app (ID is actually tenant_app_id)
        if self.tenant_sharepoint_app_repo:
            tenant_app = await self.tenant_sharepoint_app_repo.get_by_id(user_integration_id)
            if tenant_app and tenant_app.is_active:
                return await self.sharepoint_preview_service.get_preview_info_with_app(
                    tenant_app=tenant_app
                )

        from intric.main.exceptions import NotFoundException
        raise NotFoundException("Integration not found")
