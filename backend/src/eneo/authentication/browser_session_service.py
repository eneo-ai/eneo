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
a browser session it re-runs authentication (``SessionWatch``) and ends at the
token's expiry. A WebSocket keeps its user for as long as it is open, so a
browser session's token cannot open one.
"""

import asyncio
import contextlib
import secrets
import time
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

import sqlalchemy as sa
from dependency_injector import providers
from fastapi import HTTPException, Request, status

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
# How long sign-out or that check waits for the database, from taking a
# connection to the commit, before it gives up (503, or the response ends).
STORE_DEADLINE_SECONDS = 5.0


@contextlib.asynccontextmanager
async def _store_transaction(session: AsyncSession) -> AsyncGenerator[None]:
    """A transaction on ``session`` that ends within ``STORE_DEADLINE_SECONDS``.

    The database itself gives up on a statement, a lock wait included, after
    half of it, so a slow store normally fails as an error the transaction
    rolls back. The deadline covers the rest (the connection, the commit, a
    store that stops answering); its cancellation rolls back as well, and the
    connection goes back to the pool when the session closes.
    """
    async with asyncio.timeout(STORE_DEADLINE_SECONDS), session.begin():
        limit = str(int(STORE_DEADLINE_SECONDS * 500))
        await session.execute(
            sa.text(
                "SELECT set_config('lock_timeout', :limit, true),"
                " set_config('statement_timeout', :limit, true)"
            ),
            {"limit": limit},
        )
        yield


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
        if (
            payload.sid is None
            or await self.session.scalar(
                sa.select(BrowserSessions.sid).where(
                    BrowserSessions.sid == payload.sid,
                    BrowserSessions.user_id == payload.user_id,
                    BrowserSessions.tenant_id == payload.tenant_id,
                    BrowserSessions.expires_at > datetime.now(timezone.utc),
                )
            )
            is None
        ):
            raise AuthenticationException("Could not validate token credentials.")

    async def end(self, token: str) -> None:
        """Delete the session a sign-out's cookie names.

        Only a token that meets the whole local-token contract (signature,
        issuer, audience, expiry, typed claims) names a session; any other
        cookie, or a token without ``sid``, has nothing to revoke. The account
        is not checked, so a restricted user can still sign out. A row already
        gone is success: a retry after a lost response still signs out.

        Commits on its own, outside any request transaction. When the deletion
        cannot be confirmed within ``STORE_DEADLINE_SECONDS``, raises 503: the
        cookie stays, as the handle for a retry.
        """
        try:
            payload = self._verified_payload(token)
        except AuthenticationException:
            return
        if payload.sid is None:
            return
        try:
            async with _store_transaction(self.session):
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
    """Whether a response that stays open may still serve the browser session
    its request was admitted under.

    The response asks between messages. Every ``RECHECK_SECONDS`` the
    request's authentication runs again for the token's claims
    (``UserService.authenticate_payload``), in a database session of its own
    held only for that check, so what refuses a new request ends the response
    too: sign-out, a password change, signing out everywhere, a deactivated
    account or a suspended tenant. In between, the answer is the clock against
    the token's expiry. A refusal, the expiry or a check that fails or does
    not finish within ``STORE_DEADLINE_SECONDS`` ends the response, and the
    client reconnects through ordinary authentication.
    """

    def __init__(self, payload: JWTPayload, request: Request):
        self._payload = payload
        self._request = request
        self._admitted = True
        # The request has just authenticated.
        self._next_check = time.monotonic() + RECHECK_SECONDS

    async def __call__(self) -> bool:
        if not self._admitted or time.time() >= self._payload.exp:
            return False
        if time.monotonic() >= self._next_check:
            self._next_check = time.monotonic() + RECHECK_SECONDS
            self._admitted = await self._recheck()
        # The check can finish after the token expired.
        return self._admitted and time.time() < self._payload.exp

    async def _recheck(self) -> bool:
        # The container module imports this one.
        from eneo.main.container.container import Container

        try:
            async with sessionmanager.session() as session, _store_transaction(session):
                container = Container(session=providers.Object(session))
                await container.user_service().authenticate_payload(
                    self._payload, self._request
                )
            return True
        except AuthenticationException:
            return False
        except Exception as exc:
            logger.warning(
                "browser_session_recheck_failed",
                extra={
                    "user_id": str(self._payload.user_id),
                    "tenant_id": str(self._payload.tenant_id),
                    "error_type": type(exc).__name__,
                },
            )
            return False
