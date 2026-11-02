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
admitted before sign-out may still finish. The job-event stream
(``GET /jobs/events/``) stays open until the client leaves, so while it serves
a browser session it re-runs admission (``SessionWatch``) and ends at the
session's expiry. A WebSocket keeps its user for as long as it is open, so a
browser session's token cannot open one.
"""

import secrets
import time
from datetime import datetime, timezone
from uuid import UUID

import sqlalchemy as sa
from fastapi import HTTPException, status

from eneo.authentication.auth_models import JWTPayload
from eneo.authentication.auth_service import AuthService
from eneo.database.database import AsyncSession, sessionmanager
from eneo.database.tables.browser_sessions_table import BrowserSessions
from eneo.main.config import get_settings
from eneo.main.exceptions import AuthenticationException
from eneo.main.logging import get_logger

logger = get_logger(__name__)

# How often a response that stays open re-runs admission for its session.
RECHECK_SECONDS = 30.0


class BrowserSessionService:
    def __init__(self, session: AsyncSession, auth_service: AuthService):
        self.session = session
        self.auth_service = auth_service

    async def start(self, token: str) -> str:
        """Record a browser session for the token a sign-in just issued.

        Returns the token the session cookie carries: the same claims and
        expiry with a new ``sid``. Runs in the sign-in's transaction, so the
        cookie is sent only once the row is committed. The user's expired
        rows are deleted here too.
        """
        payload = self._verified_payload(token)
        # ponytail: a user who never signs in again keeps expired rows until
        # the user is deleted; join a daily maintenance job if that grows.
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
        sid = payload.sid
        if (
            sid is None
            or await self.expires_at(sid, payload.user_id, payload.tenant_id) is None
        ):
            raise AuthenticationException("Could not validate token credentials.")

    async def expires_at(
        self, sid: str, user_id: UUID, tenant_id: UUID
    ) -> datetime | None:
        """When an admitted session ends (its token's ``exp``); None once it has."""
        return await self.session.scalar(
            sa.select(BrowserSessions.expires_at).where(
                BrowserSessions.sid == sid,
                BrowserSessions.user_id == user_id,
                BrowserSessions.tenant_id == tenant_id,
                BrowserSessions.expires_at > datetime.now(timezone.utc),
            )
        )

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


class SessionWatch:
    """Whether the browser session a response that stays open was admitted
    under still lasts.

    The response asks between messages. Every ``RECHECK_SECONDS``, the first
    time included, admission's query runs again in a database session of its
    own, held only for that query; in between, the answer is the clock against
    the session's expiry. A refusal, the expiry or a check that fails ends the
    response, and the client reconnects through ordinary admission.
    """

    def __init__(self, sid: str, user_id: UUID, tenant_id: UUID):
        self._session = (sid, user_id, tenant_id)
        self._expires_at: datetime | None = None
        self._next_check = float("-inf")

    async def __call__(self) -> bool:
        if time.monotonic() >= self._next_check:
            self._next_check = time.monotonic() + RECHECK_SECONDS
            self._expires_at = await self._recheck()
        return (
            self._expires_at is not None
            and datetime.now(timezone.utc) < self._expires_at
        )

    async def _recheck(self) -> datetime | None:
        try:
            async with sessionmanager.session() as session, session.begin():
                service = BrowserSessionService(session, AuthService())
                return await service.expires_at(*self._session)
        except Exception as exc:
            _, user_id, tenant_id = self._session
            logger.warning(
                "browser_session_recheck_failed",
                extra={
                    "user_id": str(user_id),
                    "tenant_id": str(tenant_id),
                    "error_type": type(exc).__name__,
                },
            )
            return None
