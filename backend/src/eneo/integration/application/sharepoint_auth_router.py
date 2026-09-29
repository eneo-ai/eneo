import logging
from typing import TYPE_CHECKING, Optional

from eneo.integration.application.tenant_sharepoint_app_service import (
    TenantSharePointAppService,
)
from eneo.integration.domain.entities.oauth_token import SharePointToken
from eneo.integration.infrastructure.auth_service.service_account_auth_service import (
    ServiceAccountAuthService,
)
from eneo.integration.infrastructure.auth_service.tenant_app_auth_service import (
    TenantAppAuthService,
)
from eneo.integration.infrastructure.oauth_token_service import OauthTokenService
from eneo.integration.presentation.models import IntegrationType

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
        tenant_app_service: TenantSharePointAppService,
        tenant_app_auth_service: TenantAppAuthService,
        oauth_token_service: OauthTokenService,
        service_account_auth_service: Optional[ServiceAccountAuthService] = None,
    ) -> None:
        super().__init__()
        self.tenant_app_service = tenant_app_service
        self.tenant_app_auth_service = tenant_app_auth_service
        self.oauth_token_service = oauth_token_service
        self.service_account_auth_service = (
            service_account_auth_service or ServiceAccountAuthService()
        )

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
            if tenant_app.is_service_account():
                # Service account: delegated permissions via refresh token
                token_response = (
                    await self.service_account_auth_service.refresh_access_token(
                        tenant_app
                    )
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
                    },
                )
            else:
                # Tenant app: application permissions via client credentials
                access_token = await self.tenant_app_auth_service.get_access_token(
                    tenant_app
                )
                logger.info(
                    "Tenant app token acquired successfully",
                    extra={
                        "tenant_app_id": str(tenant_app.id),
                        "has_token": bool(access_token),
                    },
                )
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
