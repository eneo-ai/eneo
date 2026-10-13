"""Organisation-level SharePoint access tokens with credential health recording.

Tenant-app (client credentials) and service-account (refresh token) tokens are
acquired through container singletons that hold no session. This provider is
the one place that turns a token-endpoint outcome into persisted health on the
``TenantSharePointApp`` row, so every caller (sync, browsing, webhooks,
subscription maintenance, admin tests) reports the same way.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Awaitable, Callable, Optional, Protocol, cast

import httpx
import sqlalchemy as sa

from eneo.database.database import sessionmanager
from eneo.database.tables.tenant_sharepoint_app_table import (
    TenantSharePointApp as TenantSharePointAppDBModel,
)
from eneo.integration.domain.entities.tenant_sharepoint_app import (
    AUTH_STATUS_OK,
    TenantSharePointApp,
)
from eneo.main.logging import get_logger

if TYPE_CHECKING:
    from eneo.integration.infrastructure.auth_service.service_account_auth_service import (
        ServiceAccountAuthService,
    )
    from eneo.integration.infrastructure.auth_service.tenant_app_auth_service import (
        TenantAppAuthService,
    )

logger = get_logger(__name__)

AccessTokenProvider = Callable[[], Awaitable[str]]


class TenantAppWriter(Protocol):
    async def update(self, obj: TenantSharePointApp) -> TenantSharePointApp: ...


CREDENTIALS_INVALID_MESSAGE = (
    "SharePoint credentials are invalid or expired; an administrator must "
    "reconnect the integration"
)

# Token endpoint error codes that mean the stored credentials themselves are
# refused. Anything else (5xx, timeouts, throttling) is transient and is not
# recorded as credential failure.
_CREDENTIAL_ERROR_CODES = frozenset(
    {"invalid_grant", "invalid_client", "interaction_required", "unauthorized_client"}
)

# A cached tenant-app token is reused for up to an hour; the success stamp is
# refreshed at most this often so browsing does not write the row per request.
_SUCCESS_PERSIST_INTERVAL = timedelta(minutes=15)
_HEALTH_WRITE_LOCK_TIMEOUT = "2s"


class SharePointCredentialsInvalidError(Exception):
    """The token endpoint refused the stored credentials; retrying cannot help."""

    def __init__(self, detail: str) -> None:
        super().__init__(CREDENTIALS_INVALID_MESSAGE)
        self.detail = detail


def _error_body(exc: httpx.HTTPStatusError) -> dict[str, object]:
    try:
        body = cast(object, exc.response.json())
    except Exception:
        return {}
    return cast(dict[str, object], body) if isinstance(body, dict) else {}


def summarize_token_endpoint_error(exc: httpx.HTTPStatusError) -> str:
    """Operator-facing reason without Microsoft's trace and correlation ids."""
    body = _error_body(exc)
    description = body.get("error_description")
    if isinstance(description, str) and description:
        return description.split("\r\n")[0].split(" Trace ID:")[0].strip()
    code = body.get("error")
    if isinstance(code, str) and code:
        return code
    return f"HTTP {exc.response.status_code}"


def describe_credential_failure(exc: BaseException) -> Optional[str]:
    """Reason when ``exc`` is a token-endpoint refusal of the credentials, else None."""
    if isinstance(exc, SharePointCredentialsInvalidError):
        return exc.detail
    if not isinstance(exc, httpx.HTTPStatusError):
        return None
    code = _error_body(exc).get("error")
    if exc.response.status_code != 401 and code not in _CREDENTIAL_ERROR_CODES:
        return None
    return summarize_token_endpoint_error(exc)


async def persist_auth_health(
    app: TenantSharePointApp, *, fallback_repo: TenantAppWriter
) -> None:
    """Write the app's health columns so they survive the caller's rollback.

    A credential failure usually ends the request or job with an error, which
    rolls back its transaction. The columns are therefore written on their own
    connection. If that connection cannot lock the row within a short timeout
    (the caller's transaction already updated it), the write falls back to the
    caller's transaction instead of waiting on itself.
    """
    values = {
        "last_auth_error": app.last_auth_error,
        "last_auth_error_at": app.last_auth_error_at,
        "last_auth_success_at": app.last_auth_success_at,
    }
    try:
        async with sessionmanager.session() as session, session.begin():
            await session.execute(
                sa.text(f"SET LOCAL lock_timeout = '{_HEALTH_WRITE_LOCK_TIMEOUT}'")
            )
            await session.execute(
                sa.update(TenantSharePointAppDBModel)
                .where(TenantSharePointAppDBModel.id == app.id)
                .values(**values)
            )
        return
    except Exception as exc:
        logger.warning(
            "Could not record SharePoint credential health for app %s on its own "
            "connection (%s); recording in the current transaction instead",
            app.id,
            exc,
        )
    try:
        await fallback_repo.update(app)
    except Exception as exc:
        logger.warning(
            "Could not record SharePoint credential health for app %s: %s",
            app.id,
            exc,
        )


class OrgTokenProvider:
    """Acquire organisation tokens and record the outcome on the tenant app."""

    def __init__(
        self,
        tenant_app_repo: TenantAppWriter,
        tenant_app_auth_service: "TenantAppAuthService",
        service_account_auth_service: "ServiceAccountAuthService",
    ) -> None:
        super().__init__()
        self.tenant_app_repo = tenant_app_repo
        self.tenant_app_auth_service = tenant_app_auth_service
        self.service_account_auth_service = service_account_auth_service

    async def get_access_token(
        self, app: TenantSharePointApp, *, force_refresh: bool = False
    ) -> str:
        """An access token for ``app``, persisting rotation and health.

        Raises:
            SharePointCredentialsInvalidError: the token endpoint refused the
                credentials; the failure has been recorded on the app.
        """
        try:
            if app.is_service_account():
                token_data = (
                    await self.service_account_auth_service.refresh_access_token(app)
                )
                access_token = token_data["access_token"]
                new_refresh_token = token_data.get("refresh_token")
                if (
                    new_refresh_token
                    and new_refresh_token != app.service_account_refresh_token
                ):
                    app.update_refresh_token(new_refresh_token)
                self._mark_success(app)
                # Every service-account call is a real token round trip and may
                # have rotated the refresh token.
                await self.tenant_app_repo.update(app)
            else:
                access_token = await self.tenant_app_auth_service.get_access_token(
                    app, force_refresh=force_refresh
                )
                if self._mark_success(app):
                    await self.tenant_app_repo.update(app)
        except Exception as exc:
            detail = describe_credential_failure(exc)
            if detail is None:
                raise
            await self._record_failure(app, detail)
            raise SharePointCredentialsInvalidError(detail) from exc
        return access_token

    def access_token_provider(self, app: TenantSharePointApp) -> AccessTokenProvider:
        """A callback that re-acquires a fresh token, for Graph clients on 401."""

        async def provide() -> str:
            return await self.get_access_token(app, force_refresh=True)

        return provide

    async def test_connection(
        self, app: TenantSharePointApp
    ) -> tuple[bool, Optional[str]]:
        """A full token round trip for a stored app, recording the outcome."""
        try:
            await self.get_access_token(app, force_refresh=True)
        except SharePointCredentialsInvalidError as exc:
            return False, exc.detail
        except httpx.HTTPStatusError as exc:
            return False, summarize_token_endpoint_error(exc)
        except Exception as exc:
            return False, str(exc)
        return True, None

    @staticmethod
    def _mark_success(app: TenantSharePointApp) -> bool:
        """Stamp the success in memory; True when the row should be written."""
        now = datetime.now(timezone.utc)
        last = app.last_auth_success_at
        stale = (
            not isinstance(last, datetime) or now - last >= _SUCCESS_PERSIST_INTERVAL
        )
        changed = app.auth_status != AUTH_STATUS_OK
        app.mark_auth_success(now)
        return stale or changed

    async def _record_failure(self, app: TenantSharePointApp, detail: str) -> None:
        app.mark_auth_failure(detail, datetime.now(timezone.utc))
        logger.warning(
            "SharePoint credentials refused for tenant app %s (%s): %s",
            app.id,
            app.auth_method,
            detail,
        )
        await persist_auth_health(app, fallback_repo=self.tenant_app_repo)
