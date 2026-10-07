from typing import TYPE_CHECKING
from uuid import UUID

from eneo.integration.domain.entities.integration_preview import IntegrationPreview
from eneo.main.exceptions import BadRequestException

if TYPE_CHECKING:
    from eneo.integration.application.user_integration_service import (
        UserIntegrationService,
    )
    from eneo.integration.domain.repositories.oauth_token_repo import (
        OauthTokenRepository,
    )
    from eneo.integration.infrastructure.preview_service.confluence_preview_service import (
        ConfluencePreviewService,
    )
    from eneo.integration.infrastructure.preview_service.sharepoint_preview_service import (
        SharePointPreviewService,
    )


class IntegrationPreviewService:
    def __init__(
        self,
        oauth_token_repo: "OauthTokenRepository",
        user_integration_service: "UserIntegrationService",
        confluence_preview_service: "ConfluencePreviewService",
        sharepoint_preview_service: "SharePointPreviewService",
    ) -> None:
        self.oauth_token_repo = oauth_token_repo
        self.user_integration_service = user_integration_service
        self.confluence_preview_service = confluence_preview_service
        self.sharepoint_preview_service = sharepoint_preview_service

    async def get_preview_data(
        self, user_integration_id: UUID
    ) -> list[IntegrationPreview]:
        connection = await self.user_integration_service.get_authorized_integration(
            user_integration_id
        )
        if connection.tenant_app is not None:
            return await self.sharepoint_preview_service.get_preview_info_with_app(
                tenant_app=connection.tenant_app
            )

        token = await self.oauth_token_repo.one(
            user_integration_id=connection.integration.id
        )
        if token.token_type.is_confluence:
            return await self.confluence_preview_service.get_preview_info(token=token)
        if token.token_type.is_sharepoint:
            return await self.sharepoint_preview_service.get_preview_info(token=token)
        raise BadRequestException(f"Unsupported integration type: {token.token_type}")
