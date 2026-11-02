"""Server-side browser sessions: one ``browser_sessions`` row per sign-in.

The token a browser sign-in issues carries a ``sid`` claim naming its row.
Canonical authentication (``UserService``) admits such a token, as the cookie
or as Bearer, only while the row exists, matches the token's user and tenant
and is unexpired. Sign-out deletes the row, so a copied token stops working
at once. Tokens without ``sid`` (the token login, API, module and MCP tokens)
are not browser sessions and keep their own lifetime.

The rows live in PostgreSQL, not Redis: a revoked session must stay revoked
after a crash, and restoring a Redis snapshot can bring a deleted key back.

Admission is checked when a request authenticates. Finite HTTP and SSE work
admitted before sign-out may still finish; a WebSocket keeps its user for as
long as it is open, so a browser session's token cannot open one.
"""

import secrets
from datetime import datetime, timezone

import sqlalchemy as sa
from fastapi import HTTPException, status

from eneo.authentication.auth_models import JWTPayload
from eneo.authentication.auth_service import AuthService
from eneo.database.database import AsyncSession
from eneo.database.tables.browser_sessions_table import BrowserSessions
from eneo.main.config import get_settings
from eneo.main.exceptions import AuthenticationException
from eneo.main.logging import get_logger

logger = get_logger(__name__)


class BrowserSessionService:
    def __init__(self, session: AsyncSession, auth_service: AuthService):
        self.session = session
        self.auth_service = auth_service

    async def start(self, token: str) -> str:
        """Record a browser session for the token a sign-in just issued.

        Returns the token the session cookie carries: the same claims and
        expiry with a new ``sid``. Runs in the sign-in's transaction, so the
        cookie is sent only once the row is committed. The user's expired
        rows are deleted here too; sign-out deletes the others.
        """
        payload = self._verified_payload(token)
        await self.session.execute(
            sa.delete(BrowserSessions).where(
                BrowserSessions.user_id == payload.user_id,
                BrowserSessions.expires_at <= datetime.now(timezone.utc),
            )
        )
        # 256 bits; JWTCreds.sid accepts exactly this form.
        sid = secrets.token_urlsafe(32)
        await self.session.execute(
            sa.insert(BrowserSessions).values(
                sid=sid,
                user_id=payload.user_id,
                tenant_id=payload.tenant_id,
                expires_at=datetime.fromtimestamp(payload.exp, timezone.utc),
            )
        )
        return self.auth_service.add_session_id(token, sid)

    async def admit(self, payload: JWTPayload) -> None:
        """Refuse a verified token whose browser session has ended.

        The row must exist, belong to the token's user and tenant and be
        unexpired. Independent of ``BROWSER_SESSION_ENABLED``: a ``sid`` token
        presented as Bearer is checked all the same.
        """
        found = await self.session.scalar(
            sa.select(BrowserSessions.sid).where(
                BrowserSessions.sid == payload.sid,
                BrowserSessions.user_id == payload.user_id,
                BrowserSessions.tenant_id == payload.tenant_id,
                BrowserSessions.expires_at > datetime.now(timezone.utc),
            )
        )
        if found is None:
            raise AuthenticationException("Could not validate token credentials.")

    async def end(self, token: str) -> None:
        """Delete the session a sign-out's cookie names.

        Only a token that meets the whole local-token contract (signature,
        issuer, audience, expiry, typed claims) names a session; any other
        cookie, or a token without ``sid``, has nothing to revoke. The account
        is not checked, so a restricted user can still sign out. A row already
        gone is success: a retry after a lost response still signs out.

        Commits on its own, outside any request transaction. When the deletion
        cannot be confirmed, raises 503: the cookie stays, as the handle for a
        retry.
        """
        try:
            payload = self._verified_payload(token)
        except AuthenticationException:
            return
        if payload.sid is None:
            return
        try:
            async with self.session.begin():
                await self.session.execute(
                    sa.delete(BrowserSessions).where(
                        BrowserSessions.sid == payload.sid,
                        BrowserSessions.user_id == payload.user_id,
                        BrowserSessions.tenant_id == payload.tenant_id,
                    )
                )
        except Exception as exc:
            logger.error(
                "browser_sign_out_unavailable",
                extra={
                    "user_id": str(payload.user_id),
                    "tenant_id": str(payload.tenant_id),
                    "error_type": type(exc).__name__,
                },
            )
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "sign_out_unavailable",
                    "message": "Sign-out could not be completed. Try again.",
                },
            ) from exc

    def _verified_payload(self, token: str) -> JWTPayload:
        settings = get_settings()
        return self.auth_service.get_jwt_payload(
            token,
            key=str(settings.jwt_secret),
            aud=settings.jwt_audience,
            algs=[settings.jwt_algorithm],
        )
