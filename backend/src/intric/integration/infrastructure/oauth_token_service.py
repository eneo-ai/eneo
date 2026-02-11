import asyncio
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from uuid import UUID

    from intric.integration.domain.entities.oauth_token import OauthToken
    from intric.integration.domain.repositories.oauth_token_repo import (
        OauthTokenRepository,
    )
    from intric.integration.infrastructure.auth_service.confluence_auth_service import (
        ConfluenceAuthService,
    )
    from intric.integration.infrastructure.auth_service.sharepoint_auth_service import (
        SharepointAuthService,
    )


class OauthTokenService:
    # Process-wide locks to avoid concurrent refreshes for the same token.
    _refresh_locks: dict[str, asyncio.Lock] = {}
    _refresh_locks_guard = asyncio.Lock()

    def __init__(
        self,
        oauth_token_repo: "OauthTokenRepository",
        confluence_auth_service: "ConfluenceAuthService",
        sharepoint_auth_service: "SharepointAuthService",
    ):
        self.oauth_token_repo = oauth_token_repo
        self.confluence_auth_service = confluence_auth_service
        self.sharepoint_auth_service = sharepoint_auth_service

    @classmethod
    async def _get_refresh_lock(cls, token_id: "UUID") -> asyncio.Lock:
        token_key = str(token_id)
        async with cls._refresh_locks_guard:
            lock = cls._refresh_locks.get(token_key)
            if lock is None:
                lock = asyncio.Lock()
                cls._refresh_locks[token_key] = lock
            return lock

    async def get_oauth_token_by_user_integration(
        self,
        user_integration_id: "UUID",
    ) -> Optional["OauthToken"]:
        """Get OAuth token for a specific user integration.

        Args:
            user_integration_id: The ID of the user integration

        Returns:
            The OAuth token if found, None otherwise
        """
        return await self.oauth_token_repo.one_or_none(
            user_integration_id=user_integration_id
        )

    async def refresh_and_update_token(
        self,
        token_id: "UUID",
    ) -> "OauthToken":
        lock = await self._get_refresh_lock(token_id)
        async with lock:
            token = await self.oauth_token_repo.one(id=token_id)

            if token.token_type.is_confluence:
                token_result = await self.confluence_auth_service.refresh_access_token(
                    refresh_token=token.refresh_token
                )
            elif token.token_type.is_sharepoint:
                # Get tenant_id from the user_integration to use tenant-specific configuration
                tenant_id = token.user_integration.tenant_integration.tenant_id
                token_result = await self.sharepoint_auth_service.refresh_access_token(
                    refresh_token=token.refresh_token, tenant_id=tenant_id
                )
            else:
                raise ValueError("Unknown integration type")

            token.access_token = token_result["access_token"]
            token.refresh_token = token_result["refresh_token"]

            token = await self.oauth_token_repo.update(obj=token)
            return token
