from typing import TYPE_CHECKING, Optional
from uuid import UUID

from intric.main.logging import get_logger

if TYPE_CHECKING:
    from intric.integration.domain.repositories.oauth_token_repo import (
        OauthTokenRepository,
    )
    from intric.integration.domain.repositories.user_integration_repo import (
        UserIntegrationRepository,
    )
    from intric.integration.infrastructure.oauth_token_service import (
        OauthTokenService,
    )

logger = get_logger(__name__)


class SharePointTreeService:
    def __init__(
        self,
        oauth_token_repo: "OauthTokenRepository",
        user_integration_repo: "UserIntegrationRepository",
        oauth_token_service: "OauthTokenService",
    ):
        self.oauth_token_repo = oauth_token_repo
        self.user_integration_repo = user_integration_repo
        self.oauth_token_service = oauth_token_service

    async def get_folder_tree(
        self,
        user_integration_id: UUID,
        site_id: str,
        folder_id: Optional[str] = None,
        folder_path: str = "",
    ) -> dict:
        from intric.integration.infrastructure.preview_service.sharepoint_tree_service import (
            SharePointTreeService as InfraSharePointTreeService,
        )

        user_integration = await self.user_integration_repo.one(id=user_integration_id)
        if not user_integration.authenticated:
            raise ValueError("User integration not authenticated")

        token = await self.oauth_token_repo.one(user_integration_id=user_integration_id)

        # Create a callback function for token refresh
        async def token_refresh_callback(token_id: UUID) -> dict:
            refreshed_token = await self.oauth_token_service.refresh_and_update_token(token_id)
            return {
                "access_token": refreshed_token.access_token,
                "refresh_token": refreshed_token.refresh_token,
            }

        service = InfraSharePointTreeService(
            token_refresh_callback=token_refresh_callback
        )
        tree_data = await service.get_folder_tree(
            token=token,
            site_id=site_id,
            folder_id=folder_id,
            folder_path=folder_path,
        )

        return tree_data
