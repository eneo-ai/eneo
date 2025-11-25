from typing import TYPE_CHECKING, Dict, Optional
from uuid import UUID

from intric.main.logging import get_logger

if TYPE_CHECKING:
    from intric.integration.application.sharepoint_auth_router import SharePointAuthRouter
    from intric.integration.domain.repositories.user_integration_repo import (
        UserIntegrationRepository,
    )
    from intric.spaces.space_repo import SpaceRepository

logger = get_logger(__name__)


class SharePointTreeService:
    """Service for browsing SharePoint folder structure with hybrid auth support.

    Supports both user OAuth and tenant app authentication via SharePointAuthRouter.
    """

    def __init__(
        self,
        user_integration_repo: "UserIntegrationRepository",
        sharepoint_auth_router: "SharePointAuthRouter",
        space_repo: "SpaceRepository",
    ):
        self.user_integration_repo = user_integration_repo
        self.sharepoint_auth_router = sharepoint_auth_router
        self.space_repo = space_repo

    async def get_folder_tree(
        self,
        user_integration_id: UUID,
        space_id: UUID,
        site_id: str,
        folder_id: Optional[str] = None,
        folder_path: str = "",
    ) -> dict:
        """Get folder tree from SharePoint site using hybrid authentication.

        Args:
            user_integration_id: User's integration ID
            space_id: Space context (determines auth method)
            site_id: SharePoint site ID
            folder_id: Folder ID to browse (None for root)
            folder_path: Current folder path

        Returns:
            Dictionary with folder tree structure

        Raises:
            ValueError: If integration not authenticated or space not found
        """
        from intric.integration.infrastructure.preview_service.sharepoint_tree_service import (
            SharePointTreeService as InfraSharePointTreeService,
        )

        logger.info(
            "SharePoint tree request started",
            extra={
                "user_integration_id": str(user_integration_id),
                "space_id": str(space_id),
                "site_id": site_id,
                "folder_id": folder_id,
                "folder_path": folder_path,
            }
        )

        try:
            user_integration = await self.user_integration_repo.one(id=user_integration_id)
            logger.debug(
                "User integration found",
                extra={
                    "integration_id": str(user_integration.id),
                    "authenticated": user_integration.authenticated,
                    "auth_type": user_integration.auth_type,
                    "tenant_id": str(user_integration.tenant_integration.tenant_id),
                }
            )
        except Exception as e:
            logger.error(
                f"Failed to fetch user integration: {type(e).__name__}: {str(e)}",
                extra={"user_integration_id": str(user_integration_id)},
                exc_info=True
            )
            raise ValueError(f"User integration {user_integration_id} not found") from e

        if not user_integration.authenticated:
            logger.error(
                "User integration not authenticated",
                extra={"user_integration_id": str(user_integration_id)}
            )
            raise ValueError(f"User integration {user_integration_id} is not authenticated")

        try:
            space = await self.space_repo.one(id=space_id)
            logger.debug(
                "Space found",
                extra={
                    "space_id": str(space.id),
                    "is_personal": space.is_personal(),
                    "is_organization": space.is_organization(),
                }
            )
        except Exception as e:
            logger.error(
                f"Failed to fetch space: {type(e).__name__}: {str(e)}",
                extra={"space_id": str(space_id)},
                exc_info=True
            )
            raise ValueError(f"Space {space_id} not found") from e

        if not space:
            logger.error("Space is None after fetch", extra={"space_id": str(space_id)})
            raise ValueError(f"Space {space_id} not found")

        space_type = "personal" if space.is_personal() else ("organization" if space.is_organization() else "tenant")
        logger.info(
            "Requesting token via SharePointAuthRouter",
            extra={
                "space_type": space_type,
                "is_personal": space.is_personal(),
                "user_integration_auth_type": user_integration.auth_type,
            }
        )

        try:
            token = await self.sharepoint_auth_router.get_token_for_integration(
                user_integration=user_integration,
                space=space
            )
            logger.info(
                "Token acquired successfully",
                extra={
                    "has_access_token": bool(token.access_token),
                    "token_id": str(token.id) if token.id else None,
                    "token_type": token.token_type,
                }
            )
        except Exception as e:
            logger.error(
                f"Failed to get authentication token: {type(e).__name__}: {str(e)}",
                extra={
                    "user_integration_id": str(user_integration_id),
                    "space_id": str(space_id),
                    "space_type": space_type,
                },
                exc_info=True
            )
            raise ValueError(
                f"Failed to acquire SharePoint token for integration {user_integration_id} "
                f"in {space_type} space: {str(e)}"
            ) from e

        # Create a callback function for token refresh (only used for user OAuth)
        # Tenant app tokens are auto-refreshed by TenantAppAuthService
        async def token_refresh_callback(token_id: Optional[UUID]) -> Dict[str, str]:
            if token_id is None:
                logger.debug("Token refresh callback called for tenant app token (no-op)")
                return {"access_token": token.access_token, "refresh_token": ""}

            logger.debug("Refreshing user OAuth token", extra={"token_id": str(token_id)})
            from intric.main.container.container import Container

            container = Container()
            oauth_service = container.oauth_token_service()
            refreshed_token = await oauth_service.refresh_and_update_token(token_id)
            logger.info("Token refreshed successfully", extra={"token_id": str(token_id)})
            return {
                "access_token": refreshed_token.access_token,
                "refresh_token": refreshed_token.refresh_token,
            }

        try:
            service = InfraSharePointTreeService(
                token_refresh_callback=token_refresh_callback
            )
            logger.debug("Calling infrastructure service to fetch folder tree")
            tree_data = await service.get_folder_tree(
                token=token,
                site_id=site_id,
                folder_id=folder_id,
                folder_path=folder_path,
            )
            logger.info(
                "Folder tree fetched successfully",
                extra={
                    "item_count": len(tree_data.get("items", [])),
                    "current_path": tree_data.get("current_path"),
                }
            )
            return tree_data
        except Exception as e:
            logger.error(
                f"Failed to fetch folder tree from SharePoint: {type(e).__name__}: {str(e)}",
                extra={
                    "site_id": site_id,
                    "folder_id": folder_id,
                    "folder_path": folder_path,
                },
                exc_info=True
            )
            raise ValueError(
                f"Failed to fetch SharePoint folder tree: {str(e)}"
            ) from e
