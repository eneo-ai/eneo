import logging
from typing import TYPE_CHECKING, Optional

from eneo.integration.domain.entities.oauth_token import SharePointToken
from eneo.integration.domain.value_objects import IntegrationType
from eneo.integration.infrastructure.auth_service.org_token_provider import (
    AccessTokenProvider,
    OrgTokenProvider,
    SharePointCredentialsInvalidError,
)
from eneo.integration.infrastructure.oauth_token_service import OauthTokenService

if TYPE_CHECKING:
    from eneo.integration.application.user_integration_service import (
        AuthorizedIntegration,
    )
    from eneo.integration.domain.entities.tenant_sharepoint_app import (
        TenantSharePointApp,
    )
    from eneo.integration.domain.entities.user_integration import UserIntegration

logger = logging.getLogger(__name__)


class SharePointAuthRouter:
    """Acquire tokens for an already authorized, explicitly selected connection."""

    def __init__(
        self,
        oauth_token_service: OauthTokenService,
        org_token_provider: OrgTokenProvider,
    ) -> None:
        super().__init__()
        self.oauth_token_service = oauth_token_service
        self.org_token_provider = org_token_provider

    def access_token_provider_for(
        self, connection: "AuthorizedIntegration"
    ) -> Optional[AccessTokenProvider]:
        """Re-acquisition callback for organisation connections; None for user OAuth."""
        if connection.tenant_app is None:
            return None
        return self.org_token_provider.access_token_provider(connection.tenant_app)

    async def get_token_for_integration(
        self, connection: "AuthorizedIntegration"
    ) -> SharePointToken:
        if connection.tenant_app is not None:
            return await self._get_tenant_app_token(
                connection.tenant_app, connection.integration
            )
        return await self._get_user_oauth_token(connection.integration)

    async def _get_user_oauth_token(
        self, user_integration: "UserIntegration"
    ) -> SharePointToken:
        """Get token using user OAuth (delegated permissions)."""
        logger.debug(
            "Fetching user OAuth token",
            extra={"user_integration_id": str(user_integration.id)},
        )

        try:
            oauth_token = (
                await self.oauth_token_service.get_oauth_token_by_user_integration(
                    user_integration.id
                )
            )
        except Exception as e:
            logger.error(
                f"Failed to fetch OAuth token from database: {type(e).__name__}: {str(e)}",
                extra={"user_integration_id": str(user_integration.id)},
                exc_info=True,
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
                },
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
                "resource_count": len(oauth_token.resources)
                if oauth_token.resources
                else 0,
            },
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
        self, tenant_app: "TenantSharePointApp", user_integration: "UserIntegration"
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
            },
        )

        try:
            access_token = await self.org_token_provider.get_access_token(tenant_app)
            logger.info(
                "Organisation token acquired successfully",
                extra={
                    "tenant_app_id": str(tenant_app.id),
                    "auth_method": tenant_app.auth_method,
                },
            )
        except SharePointCredentialsInvalidError:
            raise
        except Exception as e:
            logger.error(
                f"Failed to acquire token: {type(e).__name__}: {str(e)}",
                extra={
                    "tenant_app_id": str(tenant_app.id),
                    "auth_method": tenant_app.auth_method,
                },
                exc_info=True,
            )
            raise ValueError(
                f"Failed to acquire access token for tenant app {tenant_app.id} "
                f"(auth_method={tenant_app.auth_method}): {str(e)}"
            ) from e

        return SharePointToken(
            access_token=access_token,
            refresh_token="",
            token_type=IntegrationType.Sharepoint,
            user_integration=user_integration,
            resources=[],
            id=None,
            created_at=None,
            updated_at=None,
        )
