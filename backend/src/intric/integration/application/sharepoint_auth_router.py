import logging
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from intric.integration.application.tenant_sharepoint_app_service import TenantSharePointAppService
from intric.integration.domain.entities.oauth_token import SharePointToken
from intric.integration.infrastructure.auth_service.service_account_auth_service import (
    ServiceAccountAuthService,
)
from intric.integration.infrastructure.auth_service.sharepoint_auth_service import SharepointAuthService
from intric.integration.infrastructure.auth_service.tenant_app_auth_service import TenantAppAuthService
from intric.integration.infrastructure.oauth_token_service import OauthTokenService

if TYPE_CHECKING:
    from intric.integration.domain.entities.tenant_sharepoint_app import TenantSharePointApp
    from intric.integration.domain.entities.user_integration import UserIntegration
    from intric.spaces.space import Space

logger = logging.getLogger(__name__)


class SharePointAuthRouter:
    """Routes SharePoint authentication between user OAuth, tenant app, and service account.

    Authentication Strategy:
    - Personal spaces: Always use user OAuth (delegated permissions)
    - Shared/Org spaces with tenant app configured:
        - If auth_method='service_account': Use service account (delegated permissions via refresh token)
        - If auth_method='tenant_app': Use tenant app (application permissions via client credentials)
    - Shared/Org spaces without tenant app: Fallback to user OAuth with warning

    Service accounts are recommended as they provide granular access control without person-dependency.
    """

    def __init__(
        self,
        user_oauth_service: SharepointAuthService,
        tenant_app_service: TenantSharePointAppService,
        tenant_app_auth_service: TenantAppAuthService,
        oauth_token_service: OauthTokenService,
        service_account_auth_service: Optional[ServiceAccountAuthService] = None,
    ):
        self.user_oauth_service = user_oauth_service
        self.tenant_app_service = tenant_app_service
        self.tenant_app_auth_service = tenant_app_auth_service
        self.oauth_token_service = oauth_token_service
        self.service_account_auth_service = service_account_auth_service or ServiceAccountAuthService()

    async def get_token_for_integration(
        self,
        user_integration: "UserIntegration",
        space: "Space"
    ) -> SharePointToken:
        """Get an appropriate SharePoint token based on space type and integration config.

        Args:
            user_integration: The user's integration (may use tenant app or user OAuth)
            space: The space context (determines auth routing)

        Returns:
            SharePointToken with access token

        Raises:
            ValueError: If no valid authentication method is available
        """
        if space.is_personal():
            logger.debug(f"Using user OAuth for personal space {space.id}")
            return await self._get_user_oauth_token(user_integration)

        if not space.is_personal():
            tenant_app = await self.tenant_app_service.get_active_app_for_tenant(
                user_integration.tenant_integration.tenant_id
            )

            if tenant_app:
                logger.info(
                    f"Using tenant app auth for {'org' if space.is_organization() else 'shared'} "
                    f"space {space.id}"
                )
                return await self._get_tenant_app_token(tenant_app, user_integration)
            else:
                logger.warning(
                    f"No tenant app configured for tenant {user_integration.tenant_integration.tenant_id}. "
                    f"Falling back to user OAuth for {'org' if space.is_organization() else 'shared'} "
                    f"space {space.id}. This creates person-dependency!"
                )
                return await self._get_user_oauth_token(user_integration)

    async def get_token_by_auth_type(
        self,
        user_integration: "UserIntegration",
        auth_type: str
    ) -> SharePointToken:
        """Get token based on explicit auth type (for migrations and admin operations).

        Args:
            user_integration: The user integration
            auth_type: "user_oauth" or "tenant_app"

        Returns:
            SharePointToken with access token
        """
        if auth_type == "tenant_app":
            if not user_integration.tenant_app_id:
                raise ValueError(f"Integration {user_integration.id} has no tenant_app_id")

            # Note: This is a bit hacky - ideally we'd inject the repo
            if hasattr(user_integration, 'tenant_app') and user_integration.tenant_app:
                return await self._get_tenant_app_token(
                    user_integration.tenant_app,
                    user_integration
                )
            else:
                raise ValueError(f"Cannot load tenant_app for integration {user_integration.id}")

        elif auth_type == "user_oauth":
            return await self._get_user_oauth_token(user_integration)
        else:
            raise ValueError(f"Invalid auth_type: {auth_type}")

    async def _get_user_oauth_token(
        self,
        user_integration: "UserIntegration"
    ) -> SharePointToken:
        """Get token using user OAuth (delegated permissions)."""
        logger.debug(
            "Fetching user OAuth token",
            extra={"user_integration_id": str(user_integration.id)}
        )

        try:
            oauth_token = await self.oauth_token_service.get_oauth_token_by_user_integration(
                user_integration.id
            )
        except Exception as e:
            logger.error(
                f"Failed to fetch OAuth token from database: {type(e).__name__}: {str(e)}",
                extra={"user_integration_id": str(user_integration.id)},
                exc_info=True
            )
            raise ValueError(
                f"Failed to retrieve OAuth token for user integration {user_integration.id}"
            ) from e

        if not oauth_token:
            logger.error(
                "No OAuth token found for user integration",
                extra={
                    "user_integration_id": str(user_integration.id),
                    "auth_type": user_integration.auth_type,
                }
            )
            raise ValueError(
                f"No OAuth token found for user integration {user_integration.id}. "
                f"User needs to authenticate via OAuth flow."
            )

        logger.debug(
            "OAuth token found",
            extra={
                "token_id": str(oauth_token.id),
                "has_resources": bool(oauth_token.resources),
                "resource_count": len(oauth_token.resources) if oauth_token.resources else 0,
            }
        )

        return SharePointToken(
            access_token=oauth_token.access_token,
            refresh_token=oauth_token.refresh_token,
            token_type=oauth_token.token_type,
            user_integration=user_integration,
            resources=oauth_token.resources,
            id=oauth_token.id,
            created_at=oauth_token.created_at,
            updated_at=oauth_token.updated_at,
        )

    async def _get_tenant_app_token(
        self,
        tenant_app: "TenantSharePointApp",
        user_integration: "UserIntegration"
    ) -> SharePointToken:
        """Get token using tenant app or service account based on auth_method.

        If auth_method='service_account': Uses delegated permissions via refresh token
        If auth_method='tenant_app': Uses application permissions via client credentials
        """
        logger.debug(
            "Acquiring token for organization",
            extra={
                "tenant_app_id": str(tenant_app.id),
                "auth_method": tenant_app.auth_method,
                "tenant_id": str(tenant_app.tenant_id),
            }
        )

        try:
            if tenant_app.is_service_account():
                # Service account: delegated permissions via refresh token
                token_response = await self.service_account_auth_service.refresh_access_token(
                    tenant_app
                )
                access_token = token_response["access_token"]

                # Update refresh token if a new one was issued
                if "refresh_token" in token_response:
                    new_refresh_token = token_response["refresh_token"]
                    if new_refresh_token != tenant_app.service_account_refresh_token:
                        tenant_app.update_refresh_token(new_refresh_token)
                        await self.tenant_app_service.update(tenant_app)
                        logger.debug(
                            f"Updated service account refresh token for tenant {tenant_app.tenant_id}"
                        )

                logger.info(
                    "Service account token acquired successfully",
                    extra={
                        "tenant_app_id": str(tenant_app.id),
                        "service_account_email": tenant_app.service_account_email,
                    }
                )
            else:
                # Tenant app: application permissions via client credentials
                access_token = await self.tenant_app_auth_service.get_access_token(tenant_app)
                logger.info(
                    "Tenant app token acquired successfully",
                    extra={
                        "tenant_app_id": str(tenant_app.id),
                        "has_token": bool(access_token),
                    }
                )
        except Exception as e:
            logger.error(
                f"Failed to acquire token: {type(e).__name__}: {str(e)}",
                extra={
                    "tenant_app_id": str(tenant_app.id),
                    "auth_method": tenant_app.auth_method,
                },
                exc_info=True
            )
            raise ValueError(
                f"Failed to acquire access token for tenant app {tenant_app.id} "
                f"(auth_method={tenant_app.auth_method}): {str(e)}"
            ) from e

        return SharePointToken(
            access_token=access_token,
            refresh_token="",
            token_type=user_integration.tenant_integration.integration.integration_type,
            user_integration=user_integration,
            resources={},
            id=None,
            created_at=None,
            updated_at=None,
        )

    async def should_use_tenant_app(
        self,
        tenant_id: UUID,
        space: "Space"
    ) -> bool:
        """Check if tenant app auth should be used for a space.

        Returns:
            True if space is shared/org and tenant has app configured
        """
        if space.is_personal():
            return False

        tenant_app = await self.tenant_app_service.get_active_app_for_tenant(tenant_id)
        return tenant_app is not None
