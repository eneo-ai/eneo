import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from intric.integration.domain.entities.tenant_sharepoint_app import TenantSharePointApp

logger = logging.getLogger(__name__)

DEFAULT_AUTH_TIMEOUT = 30.0


class TenantAppToken:
    """Token obtained via client credentials flow (application permissions)."""

    def __init__(self, access_token: str, expires_at: datetime):
        self.access_token = access_token
        self.expires_at = expires_at

    def is_expired(self) -> bool:
        """Check if token has expired."""
        return datetime.now(timezone.utc) >= self.expires_at

    def is_expiring_soon(self, minutes: int = 5) -> bool:
        """Check if token will expire within the specified minutes."""
        threshold = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        return self.expires_at <= threshold


class TenantAppAuthService:
    """Service for authenticating with tenant SharePoint app using client credentials flow.

    This implements application permissions (not delegated), allowing access
    without user context and eliminating person-dependency.
    """

    def __init__(self):
        self._token_cache: dict[str, TenantAppToken] = {}

    async def get_access_token(
        self,
        app: TenantSharePointApp,
        force_refresh: bool = False
    ) -> str:
        """Get an access token for the tenant app.

        Implements token caching to avoid unnecessary token requests.

        Args:
            app: The tenant SharePoint app credentials
            force_refresh: Force a new token even if cached token is valid

        Returns:
            Access token string

        Raises:
            httpx.HTTPStatusError: If token acquisition fails
        """
        cache_key = str(app.id)

        if not force_refresh and cache_key in self._token_cache:
            cached_token = self._token_cache[cache_key]
            if not cached_token.is_expiring_soon():
                logger.debug(f"Using cached token for app {app.id}")
                return cached_token.access_token

        logger.info(f"Acquiring new token for tenant app {app.id}")
        token = await self._acquire_token(app)

        self._token_cache[cache_key] = token

        return token.access_token

    async def _acquire_token(
        self,
        app: TenantSharePointApp
    ) -> TenantAppToken:
        """Acquire a new access token using client credentials flow.

        This uses the OAuth 2.0 client credentials grant type, which is designed
        for server-to-server authentication without user interaction.

        Scopes are application-level (e.g., "Sites.Read.All" not "Sites.Read").
        """
        token_endpoint = f"https://login.microsoftonline.com/{app.tenant_domain}/oauth2/v2.0/token"

        data = {
            "client_id": app.client_id,
            "client_secret": app.client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials"
        }

        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    token_endpoint,
                    headers=headers,
                    data=data,
                    timeout=DEFAULT_AUTH_TIMEOUT,
                )

                if response.status_code == 200:
                    token_data = response.json()
                    access_token = token_data["access_token"]
                    expires_in = token_data["expires_in"]

                    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

                    logger.info(f"Successfully acquired token for app {app.id}, expires at {expires_at}")

                    return TenantAppToken(
                        access_token=access_token,
                        expires_at=expires_at
                    )
                else:
                    logger.error(
                        f"Failed to acquire token for app {app.id}: "
                        f"status={response.status_code}, body={response.text}"
                    )
                    response.raise_for_status()

            except httpx.HTTPError as e:
                logger.error(f"HTTP error acquiring token for app {app.id}: {e}")
                raise

    async def test_credentials(
        self,
        app: TenantSharePointApp
    ) -> tuple[bool, Optional[str]]:
        """Test if the app credentials are valid by attempting to acquire a token.

        Args:
            app: The tenant SharePoint app to test

        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        try:
            await self._acquire_token(app)
            logger.info(f"Credentials test successful for app {app.id}")
            return (True, None)
        except httpx.HTTPStatusError as e:
            # Extract user-friendly error from Microsoft response
            try:
                error_body = e.response.json()
                error_desc = error_body.get("error_description", "")
                # Strip trace/correlation IDs from the description
                if error_desc:
                    # Microsoft error_description format: "AADSTS...: Human message. Trace ID: ... Timestamp: ..."
                    error_msg = error_desc.split("\r\n")[0].split(" Trace ID:")[0].strip()
                else:
                    error_msg = error_body.get("error", f"HTTP {e.response.status_code}")
            except Exception:
                error_msg = f"HTTP {e.response.status_code}"
            logger.error(f"Credentials test failed for app {app.id}: {error_msg}")
            return (False, error_msg)
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Credentials test failed for app {app.id}: {error_msg}")
            return (False, error_msg)

    def clear_cache(self, app_id: str) -> None:
        """Clear cached token for an app."""
        self._token_cache.pop(app_id, None)
