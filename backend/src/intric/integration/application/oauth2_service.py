import json
import secrets
from typing import TYPE_CHECKING

from intric.integration.domain.entities.oauth_token import OauthToken
from intric.integration.domain.entities.user_integration import UserIntegration
from intric.integration.presentation.models import IntegrationType
from intric.main.exceptions import BadRequestException
from intric.main.logging import get_logger

if TYPE_CHECKING:
    from uuid import UUID

    import redis.asyncio as redis

    from intric.integration.domain.repositories.oauth_token_repo import (
        OauthTokenRepository,
    )
    from intric.integration.domain.repositories.tenant_integration_repo import (
        TenantIntegrationRepository,
    )
    from intric.integration.domain.repositories.user_integration_repo import (
        UserIntegrationRepository,
    )
    from intric.integration.infrastructure.auth_service.confluence_auth_service import (
        ConfluenceAuthService,
    )
    from intric.integration.infrastructure.auth_service.sharepoint_auth_service import (
        SharepointAuthService,
    )

logger = get_logger(__name__)

# CSRF state for the per-user OAuth flow. The backend generates the state, binds it
# to the initiating user + tenant integration in Redis, and requires the callback to
# echo it back — preventing auth-code injection / login-CSRF.
_OAUTH_STATE_PREFIX = "integration:oauth_state:"
_OAUTH_STATE_TTL_SECONDS = 600


class Oauth2Service:
    def __init__(
        self,
        confluence_auth_service: "ConfluenceAuthService",
        tenant_integration_repo: "TenantIntegrationRepository",
        user_integration_repo: "UserIntegrationRepository",
        oauth_token_repo: "OauthTokenRepository",
        sharepoint_auth_service: "SharepointAuthService",
        redis_client: "redis.Redis",
    ) -> None:
        super().__init__()
        self.confluence_auth_service = confluence_auth_service
        self.tenant_integration_repo = tenant_integration_repo
        self.user_integration_repo = user_integration_repo
        self.oauth_token_repo = oauth_token_repo
        self.sharepoint_auth_service = sharepoint_auth_service
        self.redis_client = redis_client

        self._auth_mapper = {
            IntegrationType.Confluence.value: self.confluence_auth_service,
            IntegrationType.Sharepoint.value: self.sharepoint_auth_service,
        }

    async def _store_oauth_state(
        self, state: str, user_id: "UUID", tenant_integration_id: "UUID"
    ) -> None:
        await self.redis_client.set(
            f"{_OAUTH_STATE_PREFIX}{state}",
            json.dumps(
                {
                    "user_id": str(user_id),
                    "tenant_integration_id": str(tenant_integration_id),
                }
            ),
            ex=_OAUTH_STATE_TTL_SECONDS,
        )

    async def _pop_oauth_state(self, state: str) -> dict[str, str] | None:
        # GETDEL is atomic — a single round-trip that returns and deletes the value
        # — so the state is genuinely single-use even under concurrent callbacks.
        raw = await self.redis_client.getdel(f"{_OAUTH_STATE_PREFIX}{state}")
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            # Corrupt payload: treat as an invalid state (caller raises a 400)
            # instead of letting a JSON error surface as a 500.
            logger.warning("Discarding corrupt OAuth state payload")
            return None

    async def start_auth(
        self,
        tenant_integration_id: "UUID",
        user_id: "UUID",
    ) -> dict[str, str]:
        tenant_integration = await self.tenant_integration_repo.one(
            id=tenant_integration_id
        )
        integration_type = tenant_integration.integration_type

        if integration_type not in self._auth_mapper:
            raise BadRequestException("Invalid integration type")

        # Backend-generated, single-use state bound to this user + integration.
        state = secrets.token_urlsafe(32)
        await self._store_oauth_state(
            state=state,
            user_id=user_id,
            tenant_integration_id=tenant_integration_id,
        )

        if integration_type == IntegrationType.Sharepoint.value:
            result = await self.sharepoint_auth_service.gen_auth_url(
                state, tenant_id=tenant_integration.tenant_id
            )
        elif integration_type == IntegrationType.Confluence.value:
            result = await self.confluence_auth_service.gen_auth_url(state)
        else:
            raise BadRequestException("Invalid integration type")

        return {"auth_url": result["auth_url"], "state": state}

    async def auth_integration(
        self,
        user_id: "UUID",
        tenant_integration_id: "UUID",
        auth_code: str,
        state: str,
    ) -> UserIntegration:
        # CSRF: the state must have been issued by us to THIS user for THIS integration.
        stored = await self._pop_oauth_state(state)
        if stored is None:
            raise BadRequestException(
                "Invalid or expired OAuth state. Please restart the authentication flow."
            )
        if stored.get("user_id") != str(user_id) or stored.get(
            "tenant_integration_id"
        ) != str(tenant_integration_id):
            logger.warning(
                "Rejected OAuth callback with mismatched state binding (user=%s, "
                "tenant_integration=%s)",
                user_id,
                tenant_integration_id,
            )
            raise BadRequestException("OAuth state does not match the request.")

        tenant_integration = await self.tenant_integration_repo.one(
            id=tenant_integration_id
        )

        authenticated_integration = await self.user_integration_repo.one_or_none(
            user_id=user_id,
            tenant_integration_id=tenant_integration.id,
            authenticated=True,
        )
        if authenticated_integration:
            return authenticated_integration

        authenticated_integration = await self.user_integration_repo.add(
            obj=UserIntegration(
                user_id=user_id,
                tenant_integration=tenant_integration,
                authenticated=True,
            )
        )

        await self._fetch_token(
            auth_code=auth_code, authenticated_integration=authenticated_integration
        )

        return authenticated_integration

    async def _fetch_token(
        self,
        auth_code: str,
        authenticated_integration: "UserIntegration",
    ) -> None:
        integration_type = authenticated_integration.integration_type
        if integration_type == IntegrationType.Sharepoint.value:
            token_result = await self.sharepoint_auth_service.exchange_token(
                auth_code,
                tenant_id=authenticated_integration.tenant_integration.tenant_id,
            )
            if token_result is None:
                raise BadRequestException("Failed to exchange SharePoint auth code")
            access_token = token_result["access_token"]
            resource_data = await self.sharepoint_auth_service.get_resources(
                access_token
            )
        elif integration_type == IntegrationType.Confluence.value:
            token_result = await self.confluence_auth_service.exchange_token(auth_code)
            if token_result is None:
                raise BadRequestException("Failed to exchange Confluence auth code")
            access_token = token_result["access_token"]
            resource_data = await self.confluence_auth_service.get_resources(
                access_token
            )
        else:
            raise BadRequestException("Invalid integration type")

        # NOTE: build unified factory interface to construct a new entity
        # so that we do not need to manually handle the creation of entities in
        # application service which violates the domain separation
        token = OauthToken(
            access_token=access_token,
            refresh_token=token_result["refresh_token"],
            token_type=IntegrationType(integration_type),
            user_integration=authenticated_integration,
            resources=resource_data,
        )
        await self.oauth_token_repo.add(obj=token)
